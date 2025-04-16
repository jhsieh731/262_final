import grpc
import sys
import pickle
import argparse
import time
import random

import raft_pb2
import raft_pb2_grpc
from logger import set_logger

logger = set_logger("raft_client", "raft_client.log")

class RaftClient:
    def __init__(self, nodes_config):
        self.nodes = nodes_config
        self.leader_id = None
        self.leader_stub = None
    
    def find_leader(self, retries=3, delay=1.0):
        """
        Find the current leader by querying nodes.
        If the leader is dead or unavailable, retry after a short delay to allow re-election.
        """
        attempt = 0
        while attempt < retries:
            for node_id, node_info in self.nodes.items():
                try:
                    addr = f"{node_info['host']}:{node_info['port']}"
                    channel = grpc.insecure_channel(addr)
                    stub = raft_pb2_grpc.RaftServiceStub(channel)
                    
                    response = stub.FindLeader(
                        raft_pb2.FindLeaderRequest(requester_id="client"),
                        timeout=1.0
                    )
                    
                    if response.leader_id:
                        # Check if the leader is alive
                        leader_addr = f"{response.host}:{response.port}"
                        leader_channel = grpc.insecure_channel(leader_addr)
                        leader_stub = raft_pb2_grpc.RaftServiceStub(leader_channel)
                        try:
                            # Try a lightweight ping (FindLeader) to the leader
                            leader_response = leader_stub.FindLeader(
                                raft_pb2.FindLeaderRequest(requester_id="client"),
                                timeout=1.0
                            )
                            if leader_response.leader_id == response.leader_id:
                                self.leader_id = response.leader_id
                                self.leader_stub = leader_stub
                                logger.info(f"Found leader: Node {response.leader_id} at {leader_addr}")
                                return True
                        except Exception:
                            # The reported leader is dead, continue searching
                            continue
                except Exception:
                    continue
            # Wait for election to finish if leader was dead
            time.sleep(delay)
            attempt += 1
        logger.warning("No leader found after retries.")
        return False
    
    def register_user(self, username, password):
        """Register a new user"""
        if not self.find_leader():
            return {"success": False, "error": "No leader available"}
        
        content = pickle.dumps({"username": username, "password": password, "addr": "client"})
        
        try:
            response = self.leader_stub.DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="register",
                    content=content,
                    commit_index=random.randint(1, 1000000)  # In a real system, this would be managed by the leader
                )
            )
            
            if response.success:
                return {"success": True, "message": f"User {username} registered successfully"}
            else:
                return {"success": False, "error": "Registration failed"}
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            return {"success": False, "error": str(e)}
    
    def login_user(self, username, password):
        """Login a user"""
        if not self.find_leader():
            return {"success": False, "error": "No leader available"}
        
        content = pickle.dumps({"username": username, "password": password, "addr": "client"})
        
        try:
            response = self.leader_stub.DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="login",
                    content=content,
                    commit_index=random.randint(1, 1000000)
                )
            )
            
            if response.success:
                return {"success": True, "message": f"User {username} logged in successfully"}
            else:
                return {"success": False, "error": "Login failed"}
        except Exception as e:
            logger.error(f"Error during login: {e}")
            return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Raft Client")
    parser.add_argument("--action", choices=["register", "login"], required=True, help="Action to perform")
    parser.add_argument("--username", required=True, help="Username")
    parser.add_argument("--password", required=True, help="Password")
    args = parser.parse_args()
    
    # Default configuration for 3 nodes
    nodes_config = {
        "1": {"host": "localhost", "port": 50051},
        "2": {"host": "localhost", "port": 50052},
        "3": {"host": "localhost", "port": 50053}
    }
    
    client = RaftClient(nodes_config)
    
    if args.action == "register":
        result = client.register_user(args.username, args.password)
    elif args.action == "login":
        result = client.login_user(args.username, args.password)
    
    print(result)


if __name__ == "__main__":
    main()
