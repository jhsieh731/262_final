import grpc
from concurrent import futures
import threading
import time
import sqlite3
import logging
import argparse
import json
import random
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "proto")))

from proto import load_balancer_pb2, load_balancer_pb2_grpc
from proto import user_cart_pb2, user_cart_pb2_grpc
from proto import inventory_pb2, inventory_pb2_grpc
from proto import raft_pb2, raft_pb2_grpc
from raft_node import RaftNode, set_raft_logger

# Constants
HEARTBEAT_INTERVAL = 2

class LoadBalancerServer(load_balancer_pb2_grpc.LoadBalancerServiceServicer):
    def __init__(self, host, port, peers, db_path, shard1_config, shard2_config, inventory_config):
        self.host = host
        self.port = port
        self.peers = peers
        self.db_path = db_path
        self.node_id = f"{host}:{port}"
        
        # Configure shard and inventory connections
        self.shard1_replicas = [(r["host"], r["port"]) for r in shard1_config]
        self.shard2_replicas = [(r["host"], r["port"]) for r in shard2_config]
        self.inventory_replicas = [(r["host"], r["port"]) for r in inventory_config]
        
        # Current leaders (to be updated via heartbeats)
        self.shard1_leader = None
        self.shard2_leader = None
        self.inventory_leader = None
        
        # Set up database connection for user-to-shard mapping
        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row
        
        # Initialize database
        self._init_db()
        
        # Set up logging
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger(f"loadbalancer_{host}_{port}")
        self.logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.logger.info(f"Load balancer started at {host}:{port}")
        print(f"Load balancer started at {host}:{port}")
        
        # Create stubs for gRPC services
        self.shard1_stubs = self._create_stub_list(self.shard1_replicas, user_cart_pb2_grpc.UserCartServiceStub)
        self.shard2_stubs = self._create_stub_list(self.shard2_replicas, user_cart_pb2_grpc.UserCartServiceStub)
        self.inventory_stubs = self._create_stub_list(self.inventory_replicas, inventory_pb2_grpc.InventoryServiceStub)
        
        # Start leader detection
        self._start_heartbeat_threads()
    
    def _init_db(self):
        """Initialize the database with user-to-shard mapping table"""
        cur = self.db_conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_shard_mapping (
                username TEXT PRIMARY KEY,
                shard_id INTEGER NOT NULL
            );
        """)
        self.db_conn.commit()
    
    def _create_stub_list(self, replicas, stub_class):
        """Create a list of stubs for the given replicas"""
        return [(addr, stub_class(grpc.insecure_channel(f"{addr[0]}:{addr[1]}"))) for addr in replicas]
    
    def _start_heartbeat_threads(self):
        """Start background threads to monitor shard leaders"""
        def monitor_shard(stubs, update_leader_fn, service_name):
            while True:
                try:
                    leader = None
                    for (host, port), stub in stubs:
                        try:
                            response = stub.Heartbeat(user_cart_pb2.HeartbeatRequest(host=host, port=port), timeout=1.0)
                            if response.is_leader:
                                leader = (host, port)
                                self.logger.debug(f"Found leader for {service_name}: {leader}")
                                break
                        except grpc.RpcError as e:
                            if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                                leader_info = e.details().split("leader:")
                                if len(leader_info) > 1:
                                    leader_addr = leader_info[1].strip()
                                    try:
                                        leader_host, leader_port = leader_addr.split(":")
                                        leader = (leader_host, int(leader_port))
                                        break
                                    except ValueError:
                                        pass
                    
                    # Update the leader if we found one
                    if leader:
                        update_leader_fn(leader)
                    else:
                        self.logger.warning(f"No {service_name} leader found")
                        
                except Exception as e:
                    self.logger.error(f"Error in {service_name} leader monitoring: {e}")
                    
                time.sleep(HEARTBEAT_INTERVAL)

        def monitor_inventory(stubs, update_leader_fn):
            while True:
                try:
                    leader = None
                    for (host, port), stub in stubs:
                        try:
                            response = stub.Heartbeat(inventory_pb2.HeartbeatRequest(host=host, port=port), timeout=1.0)
                            if response.is_leader:
                                leader = (host, port)
                                self.logger.debug(f"Found leader for inventory: {leader}")
                                break
                        except grpc.RpcError as e:
                            if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                                leader_info = e.details().split("leader:")
                                if len(leader_info) > 1:
                                    leader_addr = leader_info[1].strip()
                                    try:
                                        leader_host, leader_port = leader_addr.split(":")
                                        leader = (leader_host, int(leader_port))
                                        break
                                    except ValueError:
                                        pass
                    
                    # Update the leader if we found one
                    if leader:
                        update_leader_fn(leader)
                    else:
                        self.logger.warning(f"No inventory leader found")
                        
                except Exception as e:
                    self.logger.error(f"Error in inventory leader monitoring: {e}")
                    
                time.sleep(HEARTBEAT_INTERVAL)

        # Start the monitoring threads
        threading.Thread(target=lambda: monitor_shard(self.shard1_stubs, self.set_shard1_leader, "Shard 1"), daemon=True).start()
        threading.Thread(target=lambda: monitor_shard(self.shard2_stubs, self.set_shard2_leader, "Shard 2"), daemon=True).start()
        threading.Thread(target=lambda: monitor_inventory(self.inventory_stubs, self.set_inventory_leader), daemon=True).start()
    
    def set_shard1_leader(self, leader):
        prev = self.shard1_leader
        if prev != leader:
            self.logger.info(f"Shard 1 leader changed from {prev} to {leader}")
        self.shard1_leader = leader
    
    def set_shard2_leader(self, leader):
        prev = self.shard2_leader
        if prev != leader:
            self.logger.info(f"Shard 2 leader changed from {prev} to {leader}")
        self.shard2_leader = leader
    
    def set_inventory_leader(self, leader):
        prev = self.inventory_leader
        if prev != leader:
            self.logger.info(f"Inventory leader changed from {prev} to {leader}")
        self.inventory_leader = leader
    
    def get_shard1_stub(self):
        """Get a stub for the current shard 1 leader"""
        if self.shard1_leader:
            return next((stub for (h, p), stub in self.shard1_stubs if (h, p) == self.shard1_leader), None)
        return None
    
    def get_shard2_stub(self):
        """Get a stub for the current shard 2 leader"""
        if self.shard2_leader:
            return next((stub for (h, p), stub in self.shard2_stubs if (h, p) == self.shard2_leader), None)
        return None
    
    def get_inventory_stub(self):
        """Get a stub for the current inventory leader"""
        if self.inventory_leader:
            return next((stub for (h, p), stub in self.inventory_stubs if (h, p) == self.inventory_leader), None)
        return None
    
    def get_user_shard(self, username):
        """Get the shard ID for a user"""
        if not username:
            return None
            
        cur = self.db_conn.cursor()
        cur.execute("SELECT shard_id FROM user_shard_mapping WHERE username = ?", (username,))
        row = cur.fetchone()
        
        if row:
            return row["shard_id"]
        return None
    
    def get_stub_for_user(self, username):
        """Get the appropriate shard stub for a user"""
        shard_id = self.get_user_shard(username)
        if shard_id == 1:
            return self.get_shard1_stub()
        elif shard_id == 2:
            return self.get_shard2_stub()
        return None
    
    def apply_command(self, command):
        """Apply commands from the Raft log to the state machine."""
        try:
            cmd = json.loads(command)
            action = cmd.get("action")
            
            if action == "map_user_to_shard":
                username = cmd.get("username")
                shard_id = cmd.get("shard_id")
                
                cur = self.db_conn.cursor()
                cur.execute("""
                    INSERT INTO user_shard_mapping (username, shard_id) 
                    VALUES (?, ?)
                """, (username, shard_id))
                self.db_conn.commit()
                self.logger.info(f"Applied map_user_to_shard: user {username} -> shard {shard_id}")
            else:
                self.logger.warning(f"Unknown command action: {action}")
                
        except Exception as e:
            self.logger.error(f"Error applying command: {e}", exc_info=True)
    
    def Heartbeat(self, request, context):
        """Return whether this node is the Raft leader"""
        is_leader = hasattr(self, 'raft_node') and self.raft_node.state == "Leader"
        
        if is_leader:
            return load_balancer_pb2.HeartbeatResponse(is_leader=True)
        else:
            # If we have a reference to the leader, return it in the error details
            leader = getattr(self.raft_node, 'current_leader', None) if hasattr(self, 'raft_node') else None
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f'Not leader. Current leader: {leader if leader else "unknown"}')
            return load_balancer_pb2.HeartbeatResponse(is_leader=False)
    
    def ReplicateShardMapping(self, request, context):
        """Replicate shard mapping from leader to follower"""
        if not hasattr(self, 'raft_node'):
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft is still initializing")
            return load_balancer_pb2.Empty()
            
        if self.raft_node.state != "Leader":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details('Not leader')
            return load_balancer_pb2.Empty()
            
        command = json.dumps({
            "action": "map_user_to_shard",
            "username": request.username,
            "shard_id": request.shard_id
        })
        
        success = self.raft_node.submit_command(command)
        return load_balancer_pb2.Empty()
    
    def Login(self, request, context):
        """Handle login requests - try both shards"""
        self.logger.info(f"Login request for user: {request.username}")
        
        # Try shard 1 first
        stub1 = self.get_shard1_stub()
        if stub1:
            try:
                response = stub1.Login(request)
                if response.success:
                    # User found on shard 1, make sure mapping is stored
                    if hasattr(self, 'raft_node') and self.raft_node.state == "Leader":
                        self._map_user_to_shard(request.username, 1)
                    return response
            except grpc.RpcError as e:
                self.logger.warning(f"Error contacting shard 1 for login: {e.code()}")
        
        # If not found or error, try shard 2
        stub2 = self.get_shard2_stub()
        if stub2:
            try:
                response = stub2.Login(request)
                if response.success:
                    # User found on shard 2, make sure mapping is stored
                    if hasattr(self, 'raft_node') and self.raft_node.state == "Leader":
                        self._map_user_to_shard(request.username, 2)
                    return response
            except grpc.RpcError as e:
                self.logger.warning(f"Error contacting shard 2 for login: {e.code()}")
        
        # If we get here, user not found on either shard or both shards unavailable
        return user_cart_pb2.LoginResponse(success=False)
    
    def _map_user_to_shard(self, username, shard_id):
        """Map a user to a shard and replicate to other load balancers"""
        print(f"mapping user {username} to shard {shard_id}")
        self.logger.info(f"Mapping user {username} to shard {shard_id}")
        command = json.dumps({
            "action": "map_user_to_shard",
            "username": username,
            "shard_id": shard_id
        })
        self.raft_node.submit_command(command)
    
    def CreateAccount(self, request, context):
        """Create a new user account and assign to a shard"""
        self.logger.info(f"Create account request for user: {request.username}")

        # See if username is unique
        cur = self.db_conn.cursor()
        cur.execute("SELECT shard_id FROM user_shard_mapping WHERE username = ?", (request.username,))
        row = cur.fetchone()
        if row:
            context.set_code(grpc.StatusCode.ALREADY_EXISTS)
            context.set_details("Username already exists")
            return user_cart_pb2.CreateAccountResponse(success=False)

        # If username is unique, proceed to create account
        # Randomly select a shard
        target_shard = random.choice([1, 2])
        
        if target_shard == 1:
            stub = self.get_shard1_stub()
        else:
            stub = self.get_shard2_stub()
        
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(f"No leader available for shard {target_shard}")
            return user_cart_pb2.CreateAccountResponse(success=False)
        
        try:
            response = stub.CreateAccount(request)
            
            if response.success and hasattr(self, 'raft_node') and self.raft_node.state == "Leader":
                # Map the new user to the selected shard
                self._map_user_to_shard(request.username, target_shard)
                
            return response
            
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error creating account: {e.details()}")
            return user_cart_pb2.CreateAccountResponse(success=False)
    
    def GetInventory(self, request, context):
        """Retrieve current inventory"""
        stub = self.get_inventory_stub()
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No inventory leader available")
            return inventory_pb2.InventoryList()
            
        try:
            return stub.GetInventory(request)
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error getting inventory: {e.details()}")
            return inventory_pb2.InventoryList()
    
    def UpdateInventory(self, request, context):
        """Update inventory quantities"""
        stub = self.get_inventory_stub()
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No inventory leader available")
            return inventory_pb2.UpdateResponse(success=False)
            
        try:
            inventory_request = inventory_pb2.UpdateRequest(
                inventory_id=request.inventory_id,
                quantity_change=request.quantity_change
            )
            return stub.UpdateInventory(inventory_request)
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error updating inventory: {e.details()}")
            return inventory_pb2.UpdateResponse(success=False)
    
    def GetCart(self, request, context):
        """Get user's cart"""
        username = request.username
        stub = self.get_stub_for_user(username)
        
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No leader available for user's shard")
            return user_cart_pb2.CartResponse()
            
        try:
            return stub.GetCart(request)
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error getting cart: {e.details()}")
            return user_cart_pb2.CartResponse()
    
    def AddToCart(self, request, context):
        """Add item to cart"""
        username = request.username
        stub = self.get_stub_for_user(username)
        
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No leader available for user's shard")
            return user_cart_pb2.CartResponse()
            
        try:
            cart_request = user_cart_pb2.UpdateCartRequest(
                user_id=request.user_id,
                inventory_id=request.inventory_id,
                quantity=request.quantity
            )
            return stub.AddToCart(cart_request)
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error adding to cart: {e.details()}")
            return user_cart_pb2.CartResponse()
    
    def RemoveFromCart(self, request, context):
        """Remove item from cart"""
        username = request.username
        stub = self.get_stub_for_user(username)
        
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No leader available for user's shard")
            return user_cart_pb2.CartResponse()
            
        try:
            cart_request = user_cart_pb2.UpdateCartRequest(
                user_id=request.user_id,
                inventory_id=request.inventory_id,
                quantity=request.quantity
            )
            return stub.RemoveFromCart(cart_request)
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error removing from cart: {e.details()}")
            return user_cart_pb2.CartResponse()
    
    def Checkout(self, request, context):
        """Process checkout"""
        username = request.username
        stub = self.get_stub_for_user(username)
        
        if not stub:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No leader available for user's shard")
            return user_cart_pb2.CheckoutResponse(success=False)
            
        try:
            # First get the user's cart so we know what inventory to update
            cart_response = stub.GetCart(request)
            
            # Update inventory quantities
            inventory_stub = self.get_inventory_stub()
            if not inventory_stub:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("No inventory leader available")
                return user_cart_pb2.CheckoutResponse(success=False)
                
            for item in cart_response.items:
                inventory_request = inventory_pb2.UpdateRequest(
                    inventory_id=item.inventory_id,
                    quantity_change=-item.quantity  # Negative because we're consuming inventory
                )
                inventory_response = inventory_stub.UpdateInventory(inventory_request)
                if not inventory_response.success:
                    context.set_code(grpc.StatusCode.ABORTED)
                    context.set_details(f"Failed to update inventory for item {item.inventory_id}")
                    return user_cart_pb2.CheckoutResponse(success=False)
            
            # Complete the checkout
            return stub.Checkout(request)
            
        except grpc.RpcError as e:
            context.set_code(e.code())
            context.set_details(f"Error during checkout: {e.details()}")
            return user_cart_pb2.CheckoutResponse(success=False)


class RaftService(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self):
        self.raft_node = None

    def attach(self, raft_node):
        self.raft_node = raft_node

    def RequestVote(self, request, context):
        if not self.raft_node:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft node not ready")
            return raft_pb2.RequestVoteResponse(term=0, vote_granted=False)
        return self.raft_node.handle_request_vote(request, context)

    def AppendEntries(self, request, context):
        if not self.raft_node:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Raft node not ready")
            return raft_pb2.AppendEntriesResponse(term=0, success=False)
        return self.raft_node.handle_append_entries(request, context)


def serve(host, port, peers, db_path, config):
    """Start the load balancer server"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Initialize load balancer
    load_balancer = LoadBalancerServer(
        host=host,
        port=port,
        peers=peers,
        db_path=db_path,
        shard1_config=config["shard1"],
        shard2_config=config["shard2"],
        inventory_config=config["inventory"]
    )
    
    # Create RaftService with placeholder
    raft_service = RaftService()
    raft_pb2_grpc.add_RaftServiceServicer_to_server(raft_service, server)
    load_balancer_pb2_grpc.add_LoadBalancerServiceServicer_to_server(load_balancer, server)
    
    # Start gRPC
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    load_balancer.logger.info(f"[boot] gRPC server running at {host}:{port}")
    
    # Wait for gRPC server to fully start
    time.sleep(3.0)
    
    # Create a single raft node
    raft_node = RaftNode(
        node_id=f"{host}:{port}",
        peers=peers,
        apply_command_callback=load_balancer.apply_command
    )
    
    # Set logger for the raft node
    set_raft_logger(load_balancer.logger)
    
    # Attach to both service objects
    raft_service.attach(raft_node)
    load_balancer.raft_node = raft_node
    load_balancer.logger.info(f"RaftNode attached to RaftService")
    
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--peers", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--config", default="config.json", help="Path to config file")

    args = parser.parse_args()
    
    # Load config
    with open(args.config) as f:
        config = json.load(f)
        
    peer_list = [tuple(p.split(":")) for p in args.peers.split(",")]
    peer_list = [(h, int(p)) for h, p in peer_list]

    serve(args.host, args.port, peer_list, args.db, config)