import grpc
from concurrent import futures
import threading
import time
import random
import sqlite3
import logging
import argparse

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from proto import user_cart_pb2, user_cart_pb2_grpc

HEARTBEAT_INTERVAL = 2
LEADER_TIMEOUT = 5

class ShardServer(user_cart_pb2_grpc.UserCartServiceServicer):
    def __init__(self, host, port, peers, db_path):
        self.host = host
        self.port = port
        self.peers = peers
        self.address = (host, port)
        self.db_path = db_path

        self.is_leader = False
        self.last_seen = {}

        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row

        # logging setup
        logger = logging.getLogger(f"shard_server_{host}_{port}")
        logger.setLevel(logging.DEBUG)

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        self.logger = logger

        # Start stuff
        self._init_db()
        self._start_heartbeat_thread()
        self.logger.info(f"Shard server started at {host}:{port}")

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

    def _start_heartbeat_thread(self):
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        while True:
            for host, port in self.peers:
                try:
                    with grpc.insecure_channel(f"{host}:{port}") as channel:
                        stub = user_cart_pb2_grpc.UserCartServiceStub(channel)
                        response = stub.Heartbeat(user_cart_pb2.HeartbeatRequest(
                            host=self.host, port=self.port), timeout=0.5)
                        self.last_seen[(host, port)] = time.time()
                except grpc.RpcError:
                    pass

            alive_peers = [addr for addr in self.peers
                           if time.time() - self.last_seen.get(addr, 0) < LEADER_TIMEOUT]
            alive_peers.append(self.address)
            prev = self.is_leader
            self.is_leader = self.address == min(alive_peers)
            if self.is_leader != prev:
                if self.is_leader:
                    self.logger.info(f"Server {self.address} is now the leader. Alive peers: {alive_peers}")
                else:
                    self.logger.info(f"Server {self.address} is no longer the leader. Alive peers: {alive_peers}")

            time.sleep(HEARTBEAT_INTERVAL)

    def Heartbeat(self, request, context):
        return user_cart_pb2.HeartbeatResponse(is_leader=self.is_leader)

    def Login(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username=?", (request.username,))
        row = cur.fetchone()
        if row:
            return user_cart_pb2.LoginResponse(success=True, user_id=row["user_id"])
        return user_cart_pb2.LoginResponse(success=False)

    def CreateAccount(self, request, context):
        if not self.is_leader:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CreateAccountResponse()

        cur = self.db_conn.cursor()
        try:
            cur.execute("INSERT INTO users (username) VALUES (?)", (request.username,))
            user_id = cur.lastrowid
            self.db_conn.commit()
            self._replicate_user(user_id, request.username)
            return user_cart_pb2.CreateAccountResponse(success=True, user_id=user_id)
        except sqlite3.IntegrityError:
            return user_cart_pb2.CreateAccountResponse(success=False)
    
    def AddToCart(self, request, context):
        if not self.is_leader:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CartResponse()

        cur = self.db_conn.cursor()
        cur.execute("""
            SELECT quantity, is_deleted FROM cart 
            WHERE user_id = ? AND itinerary_id = ?
        """, (request.user_id, request.itinerary_id))
        row = cur.fetchone()

        if row:
            # Update existing cart item (even if marked deleted previously)
            new_quantity = row["quantity"] + request.quantity if not row["is_deleted"] else request.quantity
            cur.execute("""
                UPDATE cart 
                SET quantity = ?, is_deleted = 0 
                WHERE user_id = ? AND itinerary_id = ?
            """, (new_quantity, request.user_id, request.itinerary_id))
        else:
            # Insert new cart item
            cur.execute("""
                INSERT INTO cart (user_id, itinerary_id, quantity, is_deleted)
                VALUES (?, ?, ?, 0)
            """, (request.user_id, request.itinerary_id, request.quantity))

        self.db_conn.commit()
        self._replicate_cart(request.user_id, request.itinerary_id, request.quantity, False)
        return self.GetCart(user_cart_pb2.UserRequest(user_id=request.user_id), context)

    def RemoveFromCart(self, request, context):
        if not self.is_leader:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CartResponse()

        cur = self.db_conn.cursor()
        cur.execute("UPDATE cart SET is_deleted = 1 WHERE user_id = ? AND itinerary_id = ?",
                    (request.user_id, request.itinerary_id))
        self.db_conn.commit()
        self._replicate_cart(request.user_id, request.itinerary_id, 0, True)
        return self.GetCart(user_cart_pb2.UserRequest(user_id=request.user_id), context)

    def GetCart(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT itinerary_id, quantity FROM cart WHERE user_id = ? AND is_deleted = 0",
                    (request.user_id,))
        items = [user_cart_pb2.CartItem(itinerary_id=row["itinerary_id"], quantity=row["quantity"])
                 for row in cur.fetchall()]
        return user_cart_pb2.CartResponse(items=items)

    def Checkout(self, request, context):
        if not self.is_leader:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return user_cart_pb2.CheckoutResponse()
        cur = self.db_conn.cursor()
        cur.execute("UPDATE cart SET is_deleted = 1 WHERE user_id = ?", (request.user_id,))
        self.db_conn.commit()
        return user_cart_pb2.CheckoutResponse(success=True)

    def ReplicateUser(self, request, context):
        cur = self.db_conn.cursor()
        try:
            cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                        (request.user_id, request.username))
            self.db_conn.commit()
        except:
            pass
        return user_cart_pb2.Empty()

    def ReplicateCart(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT * FROM cart WHERE user_id = ? AND itinerary_id = ?",
                    (request.user_id, request.itinerary_id))
        if cur.fetchone():
            cur.execute("UPDATE cart SET quantity = ?, is_deleted = ? WHERE user_id = ? AND itinerary_id = ?",
                        (request.quantity, int(request.is_deleted), request.user_id, request.itinerary_id))
        else:
            cur.execute("INSERT INTO cart (user_id, itinerary_id, quantity, is_deleted) VALUES (?, ?, ?, ?)",
                        (request.user_id, request.itinerary_id, request.quantity, int(request.is_deleted)))
        self.db_conn.commit()
        return user_cart_pb2.Empty()

    def _replicate_user(self, user_id, username):
        for host, port in self.peers:
            try:
                with grpc.insecure_channel(f"{host}:{port}") as channel:
                    stub = user_cart_pb2_grpc.UserCartServiceStub(channel)
                    stub.ReplicateUser(user_cart_pb2.ReplicateUserRequest(
                        user_id=user_id, username=username), timeout=1)
            except grpc.RpcError:
                pass

    def _replicate_cart(self, user_id, itinerary_id, quantity, is_deleted):
        for host, port in self.peers:
            try:
                with grpc.insecure_channel(f"{host}:{port}") as channel:
                    stub = user_cart_pb2_grpc.UserCartServiceStub(channel)
                    stub.ReplicateCart(user_cart_pb2.ReplicateCartRequest(
                        user_id=user_id,
                        itinerary_id=itinerary_id,
                        quantity=quantity,
                        is_deleted=is_deleted), timeout=1)
            except grpc.RpcError:
                pass


def serve(host, port, peers, db_path):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    shard = ShardServer(host, port, peers, db_path)
    user_cart_pb2_grpc.add_UserCartServiceServicer_to_server(shard, server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
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
