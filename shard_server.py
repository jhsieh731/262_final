import grpc
from concurrent import futures
import threading
import time
import random
import sqlite3
import logging
import argparse
import json  # for encoding/decoding commands

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "proto")))

from proto import user_cart_pb2, user_cart_pb2_grpc
from proto import raft_pb2, raft_pb2_grpc
from raft_node import RaftNode

from raft_node import set_raft_logger  # 👈 you’ll define this



HEARTBEAT_INTERVAL = 2
LEADER_TIMEOUT = 5

class ShardServer(user_cart_pb2_grpc.UserCartServiceServicer):
    def __init__(self, host, port, peers, db_path):
        self.host = host
        self.port = port
        self.peers = peers
        self.address = (host, port)
        self.db_path = db_path
        # Remove old is_leader and heartbeat fields.
        
        # Establish a unique node id string, e.g., "localhost:5000"
        self.node_id = f"{host}:{port}"

        # Set up database connection, logging, etc.
        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row
        # (Logging and DB initialization code remains unchanged)
        self._init_db()

        # logger
         # Logging
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger(f"itinerary_server_{host}_{port}")
        self.logger.setLevel(logging.DEBUG)

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        # Start the Raft service in this server's gRPC server (see serve() below)
        self.logger.info(f"Shard server started at {host}:{port} with Raft node id {self.node_id}")
        print(f"Shard server started at {host}:{port} with Raft node id {self.node_id}")

    def _init_db(self):
        cur = self.db_conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cart (
                user_id INTEGER,
                itinerary_id INTEGER,
                quantity INTEGER,
                is_deleted BOOLEAN DEFAULT 0,
                PRIMARY KEY(user_id, itinerary_id)
            );
        """)
        self.db_conn.commit()

    def apply_command(self, command):
        """
        Decodes the command (a JSON string) and performs the appropriate update.
        For example, for CreateAccount, AddToCart, or RemoveFromCart operations.
        """
        try:
            cmd = json.loads(command)
        except Exception as e:
            self.logger.error(f"Failed to decode command: {command}, error: {e}")
            return

        action = cmd.get("action")
        if action == "create_account":
            username = cmd.get("username")
            cur = self.db_conn.cursor()
            try:
                cur.execute("INSERT INTO users (username) VALUES (?)", (username,))
                self.db_conn.commit()
                self.logger.info(f"Applied create_account: {username}")
            except sqlite3.IntegrityError:
                self.logger.info(f"Account already exists: {username}")
        elif action == "add_to_cart":
            user_id = cmd.get("user_id")
            itinerary_id = cmd.get("itinerary_id")
            quantity = cmd.get("quantity")
            cur = self.db_conn.cursor()
            cur.execute("""
                SELECT quantity, is_deleted FROM cart 
                WHERE user_id = ? AND itinerary_id = ?
            """, (user_id, itinerary_id))
            row = cur.fetchone()
            if row:
                new_quantity = row["quantity"] + quantity if not row["is_deleted"] else quantity
                cur.execute("""
                    UPDATE cart 
                    SET quantity = ?, is_deleted = 0 
                    WHERE user_id = ? AND itinerary_id = ?
                """, (new_quantity, user_id, itinerary_id))
            else:
                cur.execute("""
                    INSERT INTO cart (user_id, itinerary_id, quantity, is_deleted)
                    VALUES (?, ?, ?, 0)
                """, (user_id, itinerary_id, quantity))
            self.db_conn.commit()
            self.logger.info(f"Applied add_to_cart for user {user_id}, itinerary {itinerary_id}")
        elif action == "remove_from_cart":
            user_id = cmd.get("user_id")
            itinerary_id = cmd.get("itinerary_id")
            cur = self.db_conn.cursor()
            cur.execute("UPDATE cart SET is_deleted = 1 WHERE user_id = ? AND itinerary_id = ?",
                        (user_id, itinerary_id))
            self.db_conn.commit()
            self.logger.info(f"Applied remove_from_cart for user {user_id}, itinerary {itinerary_id}")
        elif action == "checkout":
            user_id = cmd.get("user_id")
            cur = self.db_conn.cursor()
            cur.execute("UPDATE cart SET is_deleted = 1 WHERE user_id = ?", (user_id,))
            self.db_conn.commit()
            self.logger.info(f"Applied checkout for user {user_id}")


    def Heartbeat(self, request, context):
        """Return whether this node is the Raft leader"""
        is_leader = hasattr(self, 'raft_node') and self.raft_node.state == "Leader"
        return user_cart_pb2.HeartbeatResponse(is_leader=is_leader)

    def Login(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username=?", (request.username,))
        row = cur.fetchone()
        if row:
            return user_cart_pb2.LoginResponse(success=True, user_id=row["user_id"])
        return user_cart_pb2.LoginResponse(success=False)

    def CreateAccount(self, request, context):
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return user_cart_pb2.CreateAccountResponse(success=False)
        if self.raft_node.state != "Leader":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CreateAccountResponse()
        # Construct command as JSON
        command = json.dumps({
            "action": "create_account",
            "username": request.username
        })
        if self.raft_node.submit_command(command):
            # You could later query the local DB to get the new account's id.
            cur = self.db_conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username=?", (request.username,))
            row = cur.fetchone()
            if row:
                return user_cart_pb2.CreateAccountResponse(success=True, user_id=row["user_id"])
        return user_cart_pb2.CreateAccountResponse(success=False)

    
    def AddToCart(self, request, context):
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return user_cart_pb2.CreateAccountResponse(success=False)
        if self.raft_node.state != "Leader":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CartResponse()

        command = json.dumps({
            "action": "add_to_cart",
            "user_id": request.user_id,
            "itinerary_id": request.itinerary_id,
            "quantity": request.quantity
        })

        success = self.raft_node.submit_command(command)
        if success:
            return self.GetCart(user_cart_pb2.UserRequest(user_id=request.user_id), context)
        else:
            return user_cart_pb2.CartResponse()

    def RemoveFromCart(self, request, context):
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return user_cart_pb2.CreateAccountResponse(success=False)
        if self.raft_node.state != "Leader":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CartResponse()

        command = json.dumps({
            "action": "remove_from_cart",
            "user_id": request.user_id,
            "itinerary_id": request.itinerary_id
        })

        success = self.raft_node.submit_command(command)
        if success:
            return self.GetCart(user_cart_pb2.UserRequest(user_id=request.user_id), context)
        else:
            return user_cart_pb2.CartResponse()


    def GetCart(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT itinerary_id, quantity FROM cart WHERE user_id = ? AND is_deleted = 0",
                    (request.user_id,))
        items = [user_cart_pb2.CartItem(itinerary_id=row["itinerary_id"], quantity=row["quantity"])
                 for row in cur.fetchall()]
        return user_cart_pb2.CartResponse(items=items)

    def Checkout(self, request, context):
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return user_cart_pb2.CreateAccountResponse(success=False)
        if self.raft_node.state != "Leader":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CheckoutResponse()

        command = json.dumps({
            "action": "checkout",
            "user_id": request.user_id
        })

        success = self.raft_node.submit_command(command)
        return user_cart_pb2.CheckoutResponse(success=success)

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
    shard = ShardServer(host, port, peers, db_path)

    # Create RaftService with placeholder
    raft_service = RaftService()
    raft_pb2_grpc.add_RaftServiceServicer_to_server(raft_service, server)
    user_cart_pb2_grpc.add_UserCartServiceServicer_to_server(shard, server)

    # Start gRPC
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    shard.logger.info(f"[boot] gRPC server running at {host}:{port}")

    # IMPORTANT: Remove the raft_node initialization from ShardServer.__init__
    # And only initialize it here after the server has started
    time.sleep(3.0)  # Wait for gRPC server to fully start
    
    # Create a single raft node
    raft_node = RaftNode(
        node_id=f"{host}:{port}",
        peers=peers,
        apply_command_callback=shard.apply_command
    )
    
    # Set logger for the raft node
    set_raft_logger(shard.logger)
    
    # Attach to both service objects
    raft_service.attach(raft_node)
    shard.raft_node = raft_node
    shard.logger.info(f"RaftNode attached to RaftService")

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
