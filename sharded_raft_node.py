import json
import time
import random
import threading
import grpc
import sys
import concurrent.futures
from concurrent import futures
import argparse
import pickle
import os

import raft_pb2
import raft_pb2_grpc
from sharded_database import ShardedDatabase
from logger import set_logger

logger = set_logger("raft_server", "raft_server.log")

class ShardedRaftNode(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self, shard_type, node_id, nodes_config):
        """Initialize a sharded Raft node
        
        Args:
            shard_type: "even" or "odd"
            node_id: Replica ID (1, 2, or 3)
            nodes_config: Configuration for all nodes in the shard
        """
        self.shard_type = shard_type
        self.node_id = node_id
        self.nodes = nodes_config
        self.peers = {n: nodes_config[n] for n in nodes_config if n != node_id}
        
        # Node state
        self.current_term = 0
        self.voted_for = None
        self.votes_received = 0
        self.last_applied = 0
        self.last_applied_data = None
        self.log = []
        
        # Volatile state
        self.state = "follower"  # "follower", "candidate", "leader"
        self.leader_id = None
        self.election_timeout = random.uniform(3, 5)
        self.last_heartbeat = time.time()
        
        # Database
        self.db = ShardedDatabase(shard_type, node_id)
        
        # gRPC stubs for peers
        self.peer_stubs = {}
        
        # Start election timeout monitor
        self.election_thread = threading.Thread(target=self.monitor_election_timeout, daemon=True)
        self.election_thread.start()
        
        # Start peer status monitor
        self.peer_status_thread = threading.Thread(target=self.monitor_peer_status, daemon=True)
        self.peer_status_thread.start()
        
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Started")
    
    def initialize_peer_stubs(self):
        """Initialize gRPC stubs for all peers"""
        for peer_id, peer_info in self.peers.items():
            addr = f"{peer_info['host']}:{peer_info['port']}"
            channel = grpc.insecure_channel(addr)
            self.peer_stubs[peer_id] = raft_pb2_grpc.RaftServiceStub(channel)
        
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Waiting for all peers to become available...")
        
        # Wait for all peers to be available (with timeout)
        start_time = time.time()
        while len(self.peer_stubs) < len(self.peers) and time.time() - start_time < 10:
            time.sleep(0.5)
        
        if len(self.peer_stubs) < len(self.peers):
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Timeout waiting for peers. Proceeding anyway.")
    
    def RequestVote(self, request, context):
        """Handle vote requests from candidates"""
        logger.debug(f"Node {self.node_id} received vote request from {request.candidate_id} for term {request.term}")
        
        # Only vote if the candidate's term is at least as high as our current term
        # and we haven't voted yet in this term or we already voted for this candidate
        if (request.term > self.current_term) or \
           (request.term == self.current_term and 
            (self.voted_for is None or self.voted_for == request.candidate_id)):
            
            # Update our term if necessary
            if request.term > self.current_term:
                self.current_term = request.term
                self.voted_for = None  # Reset vote when moving to a new term
            
            # Vote for the candidate
            self.voted_for = request.candidate_id
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Voted for {request.candidate_id} in term {self.current_term}")
            return raft_pb2.VoteResponse(term=self.current_term, vote_granted=True)
        else:
            return raft_pb2.VoteResponse(term=self.current_term, vote_granted=False)
    
    def AppendEntries(self, request, context):
        """Handle append entries (heartbeat) from leader"""
        # Reset election timeout on receiving valid AppendEntries
        if request.term >= self.current_term:
            self.last_heartbeat = time.time()
            self.current_term = request.term
            self.state = "follower"
            self.leader_id = request.leader_id
            
            # Process log entries if any
            if len(request.entries) > 0:
                for entry in request.entries:
                    logger.debug(f"Processing log entry: {entry.action}")
                    self._apply_log_entry(entry)
            
            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=True)
        else:
            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)
    
    def DBUpdate(self, request, context):
        """Handle database update requests"""
        logger.debug(f"Node {self.node_id} received DB update: {request.action}")
        
        if self.state != "leader":
            logger.warning(f"Non-leader node {self.node_id} received DB update request")
            return raft_pb2.DBUpdateResponse(success=False, applied_index=self.last_applied)
        
        # Create a log entry
        log_entry = raft_pb2.LogEntry(
            term=self.current_term,
            action=request.action,
            content=request.content,
            index=request.commit_index
        )
        
        # Reset last_applied_data before applying the log entry
        self.last_applied_data = None
        
        # Apply to local state machine
        success = self._apply_log_entry(log_entry)
        
        # Replicate to followers
        if success:
            self._replicate_to_followers([log_entry])
        
        # Use last_applied_data if it was set during log entry application
        return raft_pb2.DBUpdateResponse(success=success, applied_index=self.last_applied, applied_data=self.last_applied_data)
    
    def FindLeader(self, request, context):
        """Handle leader discovery requests"""
        logger.debug(f"Node {self.node_id} received FindLeader request from {request.requester_id}")
        
        if self.state == "leader":
            host = self.nodes[self.node_id]["host"]
            port = self.nodes[self.node_id]["port"]
            return raft_pb2.FindLeaderResponse(leader_id=self.node_id, host=host, port=port)
        elif self.leader_id:
            host = self.nodes.get(self.leader_id, {}).get("host", "")
            port = self.nodes.get(self.leader_id, {}).get("port", 0)
            return raft_pb2.FindLeaderResponse(leader_id=self.leader_id, host=host, port=port)
        else:
            return raft_pb2.FindLeaderResponse(leader_id="", host="", port=0)
    
    def _apply_log_entry(self, entry):
        """Apply a log entry to the state machine (database)"""
        logger.info(f"Applying log entry: {entry}")
        try:
            content = pickle.loads(entry.content)
            
            if entry.action == "login":
                username = content.get("username")
                password = content.get("password")
                result = self.db.login(username, password)
            elif entry.action == "register":
                username = content.get("username")
                password = content.get("password")
                result = self.db.register(username, password)
            elif entry.action == "get_user":
                user_id = content.get("user_id")
                result = self.db.get_user(user_id)
            elif entry.action == "list_users":
                result = self.db.list_users()
            elif entry.action == "check_user_exists":
                username = content.get("username")
                # Check if user exists in this shard
                user_exists = self._check_user_exists(username)
                # Create a result with applied_data
                result = {"success": True, "user_exists": user_exists}
                # We need to return this data to the client
                # We can't modify the entry directly, so we'll store it in a variable
                # that will be accessed by the DBUpdate method
                self.last_applied_data = pickle.dumps(user_exists)
            elif entry.action == "save_cart":
                logger.info("SAVECART")
                username = content.get("username")
                items = content.get("items")
                result = self.db.save_cart(username, items)
            elif entry.action == "purchase_cart":
                logger.info("PURCHASECART")
                username = content.get("username")
                result = self.db.purchase_cart(username)
            elif entry.action == "get_cart":
                logger.info("GETCART")
                username = content.get("username")
                result = self.db.get_cart(username)
                # Store the cart items in last_applied_data to return to the client
                self.last_applied_data = pickle.dumps(result["items"])
            else:
                logger.warning(f"Unknown action: {entry.action}")
                return False
            
            self.last_applied = max(self.last_applied, entry.index)
            logger.debug(f"Applied log entry {entry.index}: {entry.action}, result: {result}")
            return True
        except Exception as e:
            logger.error(f"Error applying log entry: {e}")
            return False
    
    def _replicate_to_followers(self, entries):
        """Replicate log entries to all followers"""
        for peer_id, stub in self.peer_stubs.items():
            try:
                request = raft_pb2.AppendEntriesRequest(
                    term=self.current_term,
                    leader_id=self.node_id,
                    prev_log_index=self.last_applied - 1,
                    prev_log_term=self.current_term,
                    entries=entries,
                    leader_commit=self.last_applied
                )
                
                response = stub.AppendEntries(request, timeout=1.0)
                logger.debug(f"Replicated to peer {peer_id}, success: {response.success}")
            except Exception as e:
                logger.error(f"Error replicating to peer {peer_id}: {e}")
    
    def monitor_election_timeout(self):
        """Monitor if leader fails and start an election."""
        while True:
            time.sleep(1)
            elapsed = time.time() - self.last_heartbeat
            
            if self.state != "leader" and elapsed > self.election_timeout:
                self.election_timeout = random.uniform(3, 5)
                self.voted_for = None
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Starting election for term {self.current_term + 1}")
                self.start_election()
    
    def start_election(self):
        """Start the leader election process."""
        self.state = "candidate"
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = 1  # Vote for self
        
        # Request votes from all peers
        vote_futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.peers)) as executor:
            for peer_id, stub in self.peer_stubs.items():
                request = raft_pb2.VoteRequest(
                    term=self.current_term,
                    candidate_id=self.node_id,
                    last_log_index=self.last_applied,
                    last_log_term=self.current_term
                )
                
                future = executor.submit(self._request_vote, stub, request, peer_id)
                vote_futures.append(future)
        
        # Wait for votes to come in
        for future in concurrent.futures.as_completed(vote_futures, timeout=2.0):
            try:
                vote_granted = future.result()
                if vote_granted:
                    self.votes_received += 1
                    
                    # Check if we have majority
                    if self.votes_received > (len(self.peers) + 1) // 2:
                        self.state = "leader"
                        self.leader_id = self.node_id
                        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Elected as leader for term {self.current_term}")
                        self.send_heartbeat()
                        return
            except Exception as e:
                logger.error(f"Error getting vote result: {e}")
        
        # If we didn't get enough votes, revert to follower
        if self.state == "candidate":
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Election failed; reverting to follower.")
            self.state = "follower"
            self.last_heartbeat = time.time()
    
    def _request_vote(self, stub, request, peer_id):
        """Request vote from a single peer"""
        try:
            response = stub.RequestVote(request, timeout=1.0)
            
            if response.term > self.current_term:
                self.current_term = response.term
                self.state = "follower"
                self.voted_for = None
                return False
            
            return response.vote_granted
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] RequestVote to {peer_id} failed: {e}")
            return False
    
    def send_heartbeat(self):
        """Send heartbeat messages while the node is the leader."""
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()
    
    def _heartbeat_loop(self):
        """Continuously send heartbeats while leader"""
        while self.state == "leader":
            try:
                for peer_id, stub in self.peer_stubs.items():
                    request = raft_pb2.AppendEntriesRequest(
                        term=self.current_term,
                        leader_id=self.node_id,
                        prev_log_index=self.last_applied,
                        prev_log_term=self.current_term,
                        entries=[],  # Empty for heartbeat
                        leader_commit=self.last_applied
                    )
                    
                    try:
                        response = stub.AppendEntries(request, timeout=0.5)
                        if response.term > self.current_term:
                            self.current_term = response.term
                            self.state = "follower"
                            self.voted_for = None
                            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Discovered higher term {response.term}, reverting to follower")
                            return
                    except Exception as e:
                        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Heartbeat to {peer_id} failed: {e}")
                
                time.sleep(1)  # Send heartbeat every second
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                time.sleep(1)
    
    def monitor_peer_status(self):
        """Monitor the status of peers and update peer_stubs accordingly"""
        while True:
            time.sleep(5)  # Check every 5 seconds
            for peer_id in list(self.peers.keys()):
                if peer_id not in self.peer_stubs or not self._check_peer_status(peer_id):
                    try:
                        addr = f"{self.peers[peer_id]['host']}:{self.peers[peer_id]['port']}"
                        channel = grpc.insecure_channel(addr)
                        self.peer_stubs[peer_id] = raft_pb2_grpc.RaftServiceStub(channel)
                        logger.debug(f"Reconnected to peer {peer_id} at {addr}")
                    except Exception as e:
                        logger.error(f"Failed to reconnect to peer {peer_id}: {e}")
    
    def _check_peer_status(self, peer_id):
        """Check if a peer is responsive"""
        if peer_id not in self.peer_stubs:
            return False
        
        try:
            # Use FindLeader as a lightweight ping
            request = raft_pb2.FindLeaderRequest(requester_id=self.node_id)
            self.peer_stubs[peer_id].FindLeader(request, timeout=1.0)
            return True
        except Exception:
            return False
    
    def _check_user_exists(self, username):
        """Check if a user exists in this shard's database"""
        try:
            # Query the database to check if the username exists
            self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
            count = self.db.cursor.fetchone()[0]
            result = count > 0
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Checking if user '{username}' exists: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking if user exists: {e}")
            return False
    
    def stop(self):
        """Stop the Raft node"""
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.node_id}] Server stopped")
        # Close database connection
        self.db.close()


def serve(shard_type, node_id, nodes_config, port=None):
    """Start the gRPC server for this Raft node"""
    # If port is provided, override the one in nodes_config
    if port:
        nodes_config[node_id]["port"] = port
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    node = ShardedRaftNode(shard_type, node_id, nodes_config)
    raft_pb2_grpc.add_RaftServiceServicer_to_server(node, server)
    
    server_addr = f"{nodes_config[node_id]['host']}:{nodes_config[node_id]['port']}"
    server.add_insecure_port(server_addr)
    server.start()
    
    print(f"[{shard_type.upper()} SHARD] [REPLICA {node_id}] Server started on port {nodes_config[node_id]['port']}")
    
    # Initialize peer stubs after server is started
    node.initialize_peer_stubs()
    
    if node_id == "1":
        # First node in each shard becomes the initial leader
        print(f"[{shard_type.upper()} SHARD] [REPLICA {node_id}] I am the leader")
        node.state = "leader"
        node.leader_id = node_id
        node.send_heartbeat()
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        node.stop()
        server.stop(0)
    
    return node, server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start a sharded Raft node")
    parser.add_argument("--shard", type=str, required=True, choices=["even", "odd"], help="Shard type (even or odd)")
    parser.add_argument("--id", type=str, required=True, help="Node ID (1, 2, or 3)")
    parser.add_argument("--port", type=int, help="Override port from config")
    args = parser.parse_args()
    
    # Default configuration for 3 nodes in each shard
    # Odd shard uses ports 50051-50053, Even shard uses 50054-50056
    nodes_config = {
        "1": {"host": "localhost", "port": 50051 if args.shard == "odd" else 50054},
        "2": {"host": "localhost", "port": 50052 if args.shard == "odd" else 50055},
        "3": {"host": "localhost", "port": 50053 if args.shard == "odd" else 50056}
    }
    
    serve(args.shard, args.id, nodes_config, args.port)
