import grpc
import threading
import time
import random
import logging
import sys
import os

from proto import raft_pb2, raft_pb2_grpc

# Global logger to be set by the server
_raft_logger = None

def set_raft_logger(logger):
    """Set the logger for all Raft operations"""
    global _raft_logger
    _raft_logger = logger

class RaftNode:
    def __init__(self, node_id, peers, apply_command_callback):
        """
        Initialize a Raft consensus node
        
        Args:
            node_id: Unique identifier for this node (e.g., 'localhost:5000')
            peers: List of peer addresses as (host, port) tuples
            apply_command_callback: Function to call when a command should be applied to state machine
        """
        self.node_id = node_id
        # Convert peers from (host, port) tuples to "host:port" strings
        self.peers = [f"{host}:{port}" for host, port in peers if f"{host}:{port}" != node_id]
        self.apply_command_callback = apply_command_callback
        
        # Raft persistent state
        self.current_term = 0
        self.voted_for = None
        self.log = []  # List of LogEntry objects
        
        # Raft volatile state
        self.commit_index = -1
        self.last_applied = -1
        
        # Leader state
        self.next_index = {}
        self.match_index = {}
        
        # Server state
        self.state = "Follower"

        # Synchronization
        self.lock = threading.RLock()
        
        # Election timeout related fields
        self.election_timeout = self._random_election_timeout()
        self.last_heartbeat = time.time()
        
        # Heartbeat interval (shorter than election timeout)
        self.heartbeat_interval = 0.1
        
        # Start election timer thread
        self.election_timer_thread = threading.Thread(target=self._election_timer, daemon=True)
        self.election_timer_thread.start()
        

    def _log(self, level, message):
        """Log a message using the configured logger"""
        if _raft_logger:
            if level == "DEBUG":
                _raft_logger.debug(message)
            elif level == "INFO":
                _raft_logger.info(message)
            elif level == "WARNING":
                _raft_logger.warning(message)
            elif level == "ERROR":
                _raft_logger.error(message)
    
    def _random_election_timeout(self):
        """Generate a random election timeout between 2-4 seconds"""
        return random.uniform(2.0, 4.0)
        
    def _reset_election_timer(self):
        """Reset the election timer with a new random timeout"""
        self.election_timeout = self._random_election_timeout()
        self.last_heartbeat = time.time()
        
    def _election_timer(self):
        """Election timer thread that triggers election when timeout occurs"""
        while True:
            with self.lock:
                # Skip if we're the leader - leaders don't have election timeouts
                if self.state == "Leader":
                    time.sleep(0.1)
                    continue
                    
                # Check if election timeout has elapsed
                elapsed = time.time() - self.last_heartbeat
                if elapsed > self.election_timeout:
                    self._start_election()
                    
            time.sleep(0.1)  # Sleep outside the lock
            
    def _start_election(self):
        """Start a new election for this node"""
        with self.lock:
            # Move to candidate state, increment term, vote for self
            self.state = "Candidate"
            self.current_term += 1
            self.voted_for = self.node_id
            
            self._log("INFO", f"Starting election for term {self.current_term}")
            self._reset_election_timer()
            
            # Count votes (starting with own vote)
            votes_received = 1
            votes_needed = (len(self.peers) + 1) // 2 + 1  # Majority
            
            # Request votes from all peers
            for peer_id in self.peers:
                try:
                    host, port = peer_id.split(":")
                    with grpc.insecure_channel(peer_id) as channel:
                        stub = raft_pb2_grpc.RaftServiceStub(channel)
                        
                        # Create request vote message
                        last_log_idx = len(self.log) - 1
                        last_log_term = 0
                        if last_log_idx >= 0:
                            last_log_term = self.log[last_log_idx].term
                            
                        request = raft_pb2.RequestVoteRequest(
                            term=self.current_term,
                            candidate_id=self.node_id,
                            last_log_index=last_log_idx,
                            last_log_term=last_log_term
                        )
                        
                        # Send request vote RPC
                        response = stub.RequestVote(request, timeout=1.0)
                        
                        # Process response
                        if response.term > self.current_term:
                            # Higher term found, revert to follower
                            self._log("INFO", f"Discovered higher term {response.term}, reverting to follower")
                            self.current_term = response.term
                            self.state = "Follower"
                            self.voted_for = None
                            return
                            
                        if response.vote_granted:
                            votes_received += 1
                            if votes_received >= votes_needed:
                                self._become_leader()
                                return
                                
                except Exception as e:
                    self._log("WARNING", f"Error requesting vote from {peer_id}: {str(e)}")
                    
            # If we didn't get enough votes, stay as candidate until timeout
    
    def _become_leader(self):
        """Transition to leader state and start sending heartbeats"""
        with self.lock:
            if self.state != "Candidate":
                return
                
            self.state = "Leader"
            self._log("INFO", f"Became leader for term {self.current_term}")
            
            # Initialize leader state
            for peer_id in self.peers:
                self.next_index[peer_id] = len(self.log)
                self.match_index[peer_id] = -1
                
            # Start sending heartbeats immediately
            self._send_heartbeats()
            
            # Start heartbeat thread
            thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            thread.start()
            
    def _heartbeat_loop(self):
        """Loop that periodically sends heartbeats while leader"""
        while True:
            with self.lock:
                if self.state != "Leader":
                    return  # Exit thread if no longer leader
            
            # Send heartbeats
            self._send_heartbeats()
            
            # Sleep between heartbeats
            time.sleep(self.heartbeat_interval)
            
    def _send_heartbeats(self):
        """Send AppendEntries RPCs to all peers (may contain log entries)"""
        with self.lock:
            if self.state != "Leader":
                return
                
            # For each peer, send appropriate entries
            for peer_id in self.peers:
                try:
                    # Calculate entries to send
                    next_idx = self.next_index.get(peer_id, 0)
                    prev_log_index = next_idx - 1
                    prev_log_term = 0
                    
                    if prev_log_index >= 0 and prev_log_index < len(self.log):
                        prev_log_term = self.log[prev_log_index].term
                        
                    # Entries to send (if any)
                    entries_to_send = self.log[next_idx:] if next_idx < len(self.log) else []
                    
                    # Create AppendEntries request
                    request = raft_pb2.AppendEntriesRequest(
                        term=self.current_term,
                        leader_id=self.node_id,
                        prev_log_index=prev_log_index,
                        prev_log_term=prev_log_term,
                        entries=entries_to_send,
                        leader_commit=self.commit_index
                    )
                    
                    # Send the RPC
                    host, port = peer_id.split(":")
                    with grpc.insecure_channel(peer_id) as channel:
                        stub = raft_pb2_grpc.RaftServiceStub(channel)
                        response = stub.AppendEntries(request, timeout=1.0)
                        
                        # Process response
                        if response.term > self.current_term:
                            # Higher term found, revert to follower
                            self.current_term = response.term
                            self.state = "Follower"
                            self.voted_for = None
                            return
                            
                        if response.success:
                            # Update matchIndex and nextIndex on success
                            if entries_to_send:
                                self.match_index[peer_id] = prev_log_index + len(entries_to_send)
                                self.next_index[peer_id] = self.match_index[peer_id] + 1
                                
                                # Try to update commitIndex
                                self._update_commit_index()
                        else:
                            # Decrement nextIndex and retry on failure
                            if self.next_index[peer_id] > 0:
                                self.next_index[peer_id] -= 1
                                
                except Exception as e:
                    self._log("WARNING", f"Error sending AppendEntries to {peer_id}: {str(e)}")
    
    def _update_commit_index(self):
        """Update the commit index based on majority replication"""
        if self.state != "Leader":
            return
            
        # Find N such that majority of matchIndex[i] ≥ N and log[N].term == currentTerm
        for n in range(self.commit_index + 1, len(self.log)):
            if self.log[n].term != self.current_term:
                continue
                
            # Count peers that have replicated this entry
            replication_count = 1  # Include self
            for peer_id in self.peers:
                if self.match_index.get(peer_id, -1) >= n:
                    replication_count += 1
                    
            # If majority has replicated, update commit index
            if replication_count >= (len(self.peers) + 1) // 2 + 1:
                self.commit_index = n
                self._apply_committed_entries()
            else:
                break  # If this n isn't replicated, higher n values won't be either
    
    def _apply_committed_entries(self):
        """Apply any committed but not yet applied entries to the state machine"""
        for i in range(self.last_applied + 1, self.commit_index + 1):
            if i < len(self.log):
                entry = self.log[i]
                self.apply_command_callback(entry.command)
                self.last_applied = i
    
    def handle_request_vote(self, request, context):
        """Handle incoming RequestVote RPCs"""
        self._log("DEBUG", f"Received RequestVote from {request.candidate_id} for term {request.term}")
        with self.lock:
            # If request term < current term, reject
            if request.term < self.current_term:
                return raft_pb2.RequestVoteResponse(term=self.current_term, vote_granted=False)
                
            # If request term > current term, update term and become follower
            if request.term > self.current_term:
                self.current_term = request.term
                self.state = "Follower"
                self.voted_for = None
                
            # Determine if we should grant vote
            grant_vote = False
            
            # If we haven't voted yet in this term or already voted for this candidate
            if (self.voted_for is None or self.voted_for == request.candidate_id):
                # Check if candidate's log is at least as up-to-date as ours
                last_log_idx = len(self.log) - 1
                last_log_term = 0
                if last_log_idx >= 0:
                    last_log_term = self.log[last_log_idx].term
                    
                # Candidate's log is at least as up-to-date if:
                # 1. Its last log term is higher than ours, or
                # 2. Its last log term equals ours and its log is at least as long
                if (request.last_log_term > last_log_term or
                    (request.last_log_term == last_log_term and 
                     request.last_log_index >= last_log_idx)):
                    grant_vote = True
                    self.voted_for = request.candidate_id
                    self._reset_election_timer()
                    
            return raft_pb2.RequestVoteResponse(term=self.current_term, vote_granted=grant_vote)
    
    def handle_append_entries(self, request, context):
        """Handle incoming AppendEntries RPCs (both heartbeats and log replication)"""
        self._log("DEBUG", f"Received AppendEntries from {request.leader_id} for term {request.term}")
        with self.lock:
            # If request term < current term, reject
            if request.term < self.current_term:
                return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)
                
            # Valid AppendEntries, reset election timer
            self._reset_election_timer()
            
            # If request term > current term, update and become follower
            if request.term > self.current_term:
                self.current_term = request.term
                self.state = "Follower"
                self.voted_for = None
            
            # Even if same term, if we receive AppendEntries from valid leader, become follower
            if self.state != "Follower":
                self.state = "Follower"
            
            # Log consistency check
            success = True
            
            # If prevLogIndex points beyond our log, consistency fails
            if request.prev_log_index >= len(self.log):
                success = False
            # If prevLogIndex valid but term doesn't match, consistency fails
            elif request.prev_log_index >= 0 and (
                request.prev_log_index >= len(self.log) or
                self.log[request.prev_log_index].term != request.prev_log_term
            ):
                success = False
            else:
                # Log consistency check passed, process entries
                if request.entries:
                    # Handle new entries
                    new_index = request.prev_log_index + 1
                    
                    # Delete any conflicting entries
                    if new_index < len(self.log):
                        self.log = self.log[:new_index]
                        
                    # Append new entries
                    self.log.extend(request.entries)
                
                # Update commit index if leader's is higher
                if request.leader_commit > self.commit_index:
                    self.commit_index = min(request.leader_commit, len(self.log) - 1)
                    # Apply newly committed entries
                    self._apply_committed_entries()
            
            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=success)
    
    def submit_command(self, command):
        """
        Submit a command to the log (client API)
        
        Args:
            command: The command string to be added to the log
            
        Returns:
            bool: True if command was successfully added (node is leader), False otherwise
        """
        with self.lock:
            if self.state != "Leader":
                return False
                
            # Append to log
            log_entry = raft_pb2.LogEntry(term=self.current_term, command=command)
            self.log.append(log_entry)
            
            # Update leader's matchIndex for itself
            self._log("INFO", f"Command submitted: {command[:30]}...")
            
            return True