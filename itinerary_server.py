# import grpc
# from concurrent import futures
# import threading
# import time
# import sqlite3
# import logging
# import argparse

# import sys
# import os
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# from proto import itinerary_pb2, itinerary_pb2_grpc

# HEARTBEAT_INTERVAL = 2
# LEADER_TIMEOUT = 10

# class ItineraryServer(itinerary_pb2_grpc.ItineraryServiceServicer):
#     def __init__(self, host, port, peers, db_path):
#         self.host = host
#         self.port = port
#         self.peers = peers
#         self.address = (host, port)
#         self.last_seen = {}
#         self.is_leader = False
#         self.subscribers = []

#         # Logging
#         os.makedirs("logs", exist_ok=True)
#         self.logger = logging.getLogger(f"itinerary_server_{host}_{port}")
#         self.logger.setLevel(logging.DEBUG)

#         handler = logging.StreamHandler(sys.stdout)
#         formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s")
#         handler.setFormatter(formatter)
#         self.logger.addHandler(handler)

#         self.db_conn = sqlite3.connect(db_path, check_same_thread=False)
#         self.db_conn.row_factory = sqlite3.Row

#         self._init_db()
#         self._start_heartbeat_thread()
#         self.logger.info(f"Itinerary server started at {host}:{port}")

#     def _init_db(self):
#         cur = self.db_conn.cursor()
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS itinerary (
#                 id INTEGER PRIMARY KEY AUTOINCREMENT,
#                 name TEXT,
#                 number INTEGER
#             );
#         """)
#         cur.execute("SELECT COUNT(*) FROM itinerary")
#         if cur.fetchone()[0] == 0:
#             for name in ['Flight', 'Hotel', 'Car']:
#                 cur.execute("INSERT INTO itinerary (name, number) VALUES (?, ?)", (name, 10))
#         self.db_conn.commit()
#         self.logger.info("Database initialized with default itinerary items.")
#         cur.close()

#     def _start_heartbeat_thread(self):
#         threading.Thread(target=self._heartbeat_loop, daemon=True).start()

#     def _heartbeat_loop(self):
#         while True:
#             for host, port in self.peers:
#                 try:
#                     with grpc.insecure_channel(f"{host}:{port}") as channel:
#                         stub = itinerary_pb2_grpc.ItineraryServiceStub(channel)
#                         resp = stub.Heartbeat(itinerary_pb2.HeartbeatRequest(
#                             host=self.host, port=self.port), timeout=0.5)
#                         self.last_seen[(host, port)] = time.time()
#                 except grpc.RpcError:
#                     pass

#             alive = [addr for addr in self.peers if time.time() - self.last_seen.get(addr, 0) < LEADER_TIMEOUT]
#             alive.append(self.address)
#             prev = self.is_leader
#             self.is_leader = self.address == min(alive)
#             if self.is_leader != prev:
#                 if self.is_leader:
#                     self.logger.info(f"Server {self.address} is now the leader. Alive peers: {alive}")
#                 else:
#                     self.logger.info(f"Server {self.address} is no longer the leader. Alive peers: {alive}")

#             time.sleep(HEARTBEAT_INTERVAL)

#     def Heartbeat(self, request, context):
#         # self.logger.debug(f"Heartbeat from {request.host}:{request.port}")
#         return itinerary_pb2.HeartbeatResponse(is_leader=self.is_leader)

#     def GetItinerary(self, request, context):
#         return self._get_itinerary_list()

#     def StreamItineraryChanges(self, request, context):
#         self.logger.info(f"Client {context.peer()} subscribed to itinerary stream")

#         if not self.is_leader:
#             self.logger.info("Not the leader; returning empty stream")
#             return

#         try:
#             # Send current state once
#             yield self._get_itinerary_list()

#             # Keep alive (no-op yields)
#             while True:
#                 time.sleep(60)  # Keep stream open to simulate liveness
#         except grpc.RpcError:
#             self.logger.info(f"Client {context.peer()} disconnected")



#     def UpdateItinerary(self, request, context):
#         if not self.is_leader:
#             context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
#             context.set_details("Not leader")
#             return itinerary_pb2.UpdateResponse()

#         cur = self.db_conn.cursor()
#         cur.execute("UPDATE itinerary SET number = number - ? WHERE id = ? AND number >= ?",
#                     (request.quantity_change, request.itinerary_id, request.quantity_change))
#         self.db_conn.commit()
#         self.logger.info(f"Updated itinerary {request.itinerary_id} by {request.quantity_change}")
#         cur.close()

#         self._replicate_update(request.itinerary_id, request.quantity_change)
#         self._broadcast_updates()
#         return itinerary_pb2.UpdateResponse(success=True)

#     def ReplicateItinerary(self, request, context):
#         cur = self.db_conn.cursor()
#         cur.execute("UPDATE itinerary SET number = number - ? WHERE id = ? AND number >= ?",
#                     (request.quantity_change, request.itinerary_id, request.quantity_change))
#         self.db_conn.commit()
#         self.logger.info(f"Replicated itinerary {request.itinerary_id} by {request.quantity_change}")
#         cur.close()

#         self._broadcast_updates()
#         return itinerary_pb2.Empty()

#     def _broadcast_updates(self):
#         itinerary_list = self._get_itinerary_list()
#         for context in self.subscribers[:]:
#             try:
#                 context.write(itinerary_list)
#             except grpc.RpcError:
#                 self.logger.debug(f"Client {context.peer()} disconnected")
#                 self.subscribers.remove(context)

#     def _get_itinerary_list(self):
#         cur = self.db_conn.cursor()
#         cur.execute("SELECT id, name, number FROM itinerary")
#         items = [
#             itinerary_pb2.ItineraryItem(id=row["id"], name=row["name"], number=row["number"])
#             for row in cur.fetchall()
#         ]
#         cur.close()
#         self.logger.debug(f"Fetched itinerary list: {items}")
#         return itinerary_pb2.ItineraryList(items=items)

#     def _replicate_update(self, itinerary_id, quantity_change):
#         for host, port in self.peers:
#             try:
#                 with grpc.insecure_channel(f"{host}:{port}") as channel:
#                     stub = itinerary_pb2_grpc.ItineraryServiceStub(channel)
#                     stub.ReplicateItinerary(itinerary_pb2.UpdateRequest(
#                         itinerary_id=itinerary_id,
#                         quantity_change=quantity_change
#                     ), timeout=1)
#             except grpc.RpcError:
#                 self.logger.warning(f"Failed to replicate update to {host}:{port}")
#                 pass


# def serve(host, port, peers, db_path):
#     server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
#     servicer = ItineraryServer(host, port, peers, db_path)
#     itinerary_pb2_grpc.add_ItineraryServiceServicer_to_server(servicer, server)
#     server.add_insecure_port(f"{host}:{port}")
#     server.start()
#     server.wait_for_termination()


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--host", required=True)
#     parser.add_argument("--port", type=int, required=True)
#     parser.add_argument("--peers", required=True)
#     parser.add_argument("--db", required=True)

#     args = parser.parse_args()
#     peer_list = [tuple(p.split(":")) for p in args.peers.split(",")]
#     peer_list = [(h, int(p)) for h, p in peer_list]

#     serve(args.host, args.port, peer_list, args.db)



import grpc
from concurrent import futures
import threading
import time
import sqlite3
import logging
import argparse

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from proto import itinerary_pb2, itinerary_pb2_grpc

HEARTBEAT_INTERVAL = 2
LEADER_TIMEOUT = 10

class ItineraryServer(itinerary_pb2_grpc.ItineraryServiceServicer):
    def __init__(self, host, port, peers, db_path):
        self.host = host
        self.port = port
        self.peers = peers
        self.address = (host, port)
        self.last_seen = {}
        self.is_leader = False

        self.db_conn = sqlite3.connect(db_path, check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row

        # Logging
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger(f"itinerary_server_{host}_{port}")
        self.logger.setLevel(logging.DEBUG)

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self._init_db()
        self._start_heartbeat_thread()
        self.logger.info(f"Itinerary server started at {host}:{port}")

    def _init_db(self):
        cur = self.db_conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS itinerary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                number INTEGER
            );
        """)
        cur.execute("SELECT COUNT(*) FROM itinerary")
        if cur.fetchone()[0] == 0:
            for name in ['Apple', 'Banana', 'Carrot']:
                cur.execute("INSERT INTO itinerary (name, number) VALUES (?, ?)", (name, 100))
        self.db_conn.commit()

    def _start_heartbeat_thread(self):
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        while True:
            for host, port in self.peers:
                try:
                    with grpc.insecure_channel(f"{host}:{port}") as channel:
                        stub = itinerary_pb2_grpc.ItineraryServiceStub(channel)
                        resp = stub.Heartbeat(itinerary_pb2.HeartbeatRequest(
                            host=self.host, port=self.port), timeout=0.5)
                        self.last_seen[(host, port)] = time.time()
                except grpc.RpcError:
                    pass

            alive = [addr for addr in self.peers if time.time() - self.last_seen.get(addr, 0) < LEADER_TIMEOUT]
            alive.append(self.address)
            prev = self.is_leader
            self.is_leader = self.address == min(alive)
            if self.is_leader != prev:
                if self.is_leader:
                    self.logger.info(f"Server {self.address} is now the leader. Alive: {alive}")
                else:
                    self.logger.info(f"Server {self.address} is no longer the leader. Alive: {alive}")

            time.sleep(HEARTBEAT_INTERVAL)

    def Heartbeat(self, request, context):
        return itinerary_pb2.HeartbeatResponse(is_leader=self.is_leader)

    def GetItinerary(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("SELECT id, name, number FROM itinerary")
        items = [
            itinerary_pb2.ItineraryItem(id=row["id"], name=row["name"], number=row["number"])
            for row in cur.fetchall()
        ]
        return itinerary_pb2.ItineraryList(items=items)

    def UpdateItinerary(self, request, context):
        if not self.is_leader:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("Not leader")
            return itinerary_pb2.UpdateResponse()

        cur = self.db_conn.cursor()
        cur.execute("UPDATE itinerary SET number = number - ? WHERE id = ? AND number >= ?",
                    (request.quantity_change, request.itinerary_id, request.quantity_change))
        self.db_conn.commit()
        self.logger.info(f"Updated itinerary {request.itinerary_id} by {request.quantity_change}")
        self._replicate_update(request.itinerary_id, request.quantity_change)
        return itinerary_pb2.UpdateResponse(success=True)

    def ReplicateItinerary(self, request, context):
        cur = self.db_conn.cursor()
        cur.execute("UPDATE itinerary SET number = number - ? WHERE id = ? AND number >= ?",
                    (request.quantity_change, request.itinerary_id, request.quantity_change))
        self.db_conn.commit()
        self.logger.info(f"Replicated itinerary {request.itinerary_id} by {request.quantity_change}")
        return itinerary_pb2.Empty()

    def _replicate_update(self, itinerary_id, quantity_change):
        for host, port in self.peers:
            try:
                with grpc.insecure_channel(f"{host}:{port}") as channel:
                    stub = itinerary_pb2_grpc.ItineraryServiceStub(channel)
                    stub.ReplicateItinerary(itinerary_pb2.UpdateRequest(
                        itinerary_id=itinerary_id,
                        quantity_change=quantity_change
                    ), timeout=1)
            except grpc.RpcError:
                pass


def serve(host, port, peers, db_path):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    servicer = ItineraryServer(host, port, peers, db_path)
    itinerary_pb2_grpc.add_ItineraryServiceServicer_to_server(servicer, server)
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
