import grpc
from concurrent import futures
import threading
import time
import sqlite3
import logging
import argparse
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "proto")))

from proto import itinerary_pb2, itinerary_pb2_grpc
from proto import raft_pb2, raft_pb2_grpc
from raft_node import RaftNode
from raft_node import set_raft_logger  # Assuming this exists as in shard_server.py

class ItineraryServer(itinerary_pb2_grpc.ItineraryServiceServicer):
    def __init__(self, host, port, peers, db_path):
        self.host = host
        self.port = port
        self.peers = peers
        self.db_path = db_path
        
        # Establish a unique node id string, e.g., "localhost:5000"
        self.node_id = f"{host}:{port}"

        # Set up database connection
        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row
        
        # Initialize database
        self._init_db()

        # Setup logging
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger(f"itinerary_server_{host}_{port}")
        self.logger.setLevel(logging.DEBUG)

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        self.logger.info(f"Shard server started at {host}:{port} with Raft node id {self.node_id}")
        print(f"Shard server started at {host}:{port} with Raft node id {self.node_id}")

    def _init_db(self):
        """Initialize the itinerary database"""
        cur = self.db_conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS itinerary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                number INTEGER NOT NULL DEFAULT 0
            );
        """)
        
        # Initialize with sample data if empty
        cur.execute("SELECT COUNT(*) FROM itinerary")
        if cur.fetchone()[0] == 0:
            sample_data = [
                ("Flight to Paris", 10),
                ("Hotel in Rome", 20),
                ("Car Rental in London", 15),
                ("Beach Resort in Bali", 5),
                ("Mountain Retreat in Switzerland", 8)
            ]
            for name, number in sample_data:
                cur.execute("INSERT INTO itinerary (name, number) VALUES (?, ?)", (name, number))
        
        self.db_conn.commit()

    def apply_command(self, command):
        """
        Apply commands from the Raft log to the state machine.
        Commands are JSON strings encoding operations.
        """
        try:
            cmd = json.loads(command)
            action = cmd.get("action")
            
            if action == "update_itinerary":
                itinerary_id = cmd.get("itinerary_id")
                quantity_change = cmd.get("quantity_change")
                
                cur = self.db_conn.cursor()
                # Check if we have enough inventory
                if quantity_change < 0:  # We're decreasing inventory (booking)
                    cur.execute("SELECT number FROM itinerary WHERE id = ?", (itinerary_id,))
                    row = cur.fetchone()
                    if row and row["number"] < abs(quantity_change):
                        self.logger.warning(f"Not enough inventory for item {itinerary_id}")
                        return False
                
                # Update the inventory
                cur.execute(
                    "UPDATE itinerary SET number = number + ? WHERE id = ?",
                    (quantity_change, itinerary_id)
                )
                self.db_conn.commit()
                self.logger.info(f"Applied update_itinerary: item {itinerary_id}, change {quantity_change}")
                return True
            else:
                self.logger.warning(f"Unknown command action: {action}")
                return False
        except Exception as e:
            self.logger.error(f"Error applying command: {e}", exc_info=True)
            return False

    def Heartbeat(self, request, context):
        """Return whether this node is the Raft leader"""
        is_leader = hasattr(self, 'raft_node') and self.raft_node.state == "Leader"
        
        if is_leader:
            return itinerary_pb2.HeartbeatResponse(is_leader=True)
        else:
            # If we have a reference to the leader, return it in the error details
            leader = getattr(self.raft_node, 'current_leader', None) if hasattr(self, 'raft_node') else None
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f'Not leader. Current leader: {leader if leader else "unknown"}')
            return itinerary_pb2.HeartbeatResponse(is_leader=False)

    def GetItinerary(self, request, context):
        """Get all itinerary items - read-only operation can be handled by any node"""
        cur = self.db_conn.cursor()
        cur.execute("SELECT id, name, number FROM itinerary")
        items = [
            itinerary_pb2.ItineraryItem(id=row["id"], name=row["name"], number=row["number"])
            for row in cur.fetchall()
        ]
        return itinerary_pb2.ItineraryList(items=items)

    def UpdateItinerary(self, request, context):
        """Update an itinerary item - write operation requires consensus"""
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return itinerary_pb2.UpdateResponse(success=False)
        
        if self.raft_node.state != "Leader":
            leader = getattr(self.raft_node, 'current_leader', None)
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f'Not leader. Current leader: {leader if leader else "unknown"}')
            return itinerary_pb2.UpdateResponse(success=False)

        # Construct command as JSON
        command = json.dumps({
            "action": "update_itinerary",
            "itinerary_id": request.itinerary_id,
            "quantity_change": request.quantity_change
        })
        
        success = self.raft_node.submit_command(command)
        return itinerary_pb2.UpdateResponse(success=success)

class RaftService(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self):
        self.raft_node = None

    def attach(self, raft_node):
        self.raft_node = raft_node

    def RequestVote(self, request, context):
        print(f"[RaftService RequestVote] Received RequestVote from {request.candidate_id} in term {request.term}")
        if not self.raft_node:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft node not ready")
            return raft_pb2.RequestVoteResponse(term=0, vote_granted=False)
        return self.raft_node.handle_request_vote(request, context)

    def AppendEntries(self, request, context):
        print(f"[RaftService AppendEntries] Received AppendEntries from {request.leader_id} in term {request.term}")
        if not self.raft_node:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft node not ready")
            return raft_pb2.AppendEntriesResponse(term=0, success=False)
        print("got past the raft node check")
        return self.raft_node.handle_append_entries(request, context)

def serve(host, port, peers, db_path):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    itinerary = ItineraryServer(host, port, peers, db_path)

    # Create RaftService with placeholder
    raft_service = RaftService()
    raft_pb2_grpc.add_RaftServiceServicer_to_server(raft_service, server)
    itinerary_pb2_grpc.add_ItineraryServiceServicer_to_server(itinerary, server)

    # Start gRPC
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    itinerary.logger.info(f"[boot] gRPC server running at {host}:{port}")

    # Wait for gRPC server to fully start
    time.sleep(3.0)
    
    # Create a single raft node
    raft_node = RaftNode(
        node_id=f"{host}:{port}",
        peers=peers,
        apply_command_callback=itinerary.apply_command
    )
    
    # Set logger for the raft node
    set_raft_logger(itinerary.logger)
    
    # Attach to both service objects
    raft_service.attach(raft_node)
    itinerary.raft_node = raft_node
    itinerary.logger.info(f"RaftNode attached to RaftService")

    server.wait_for_termination()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--peers", required=True)
    parser.add_argument("--db", required=True)

    args = parser.parse_args()
    peer_list = [tuple(p.split(":")) for p in args.peers.split(",")]
    peer_list = [(h, int(p)) for h, p in peer_list]

    serve(args.host, args.port, peer_list, args.db)