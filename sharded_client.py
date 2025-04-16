import grpc
import sys
import pickle
import argparse
import time
import random

import raft_pb2
import raft_pb2_grpc
from logger import set_logger

logger = set_logger("sharded_client", "sharded_client.log")

class ShardedClient:
    def __init__(self):
        # Configuration for both shards
        self.shards = {
            "odd": {
                "nodes": {
                    "1": {"host": "localhost", "port": 50051},
                    "2": {"host": "localhost", "port": 50052},
                    "3": {"host": "localhost", "port": 50053}
                },
                "leader_id": None,
                "leader_stub": None
            },
            "even": {
                "nodes": {
                    "1": {"host": "localhost", "port": 50054},
                    "2": {"host": "localhost", "port": 50055},
                    "3": {"host": "localhost", "port": 50056}
                },
                "leader_id": None,
                "leader_stub": None
            }
        }
    
    def find_leader(self, shard_type, retries=3, delay=1.0):
        """Find the current leader for a specific shard"""
        shard = self.shards[shard_type]
        
        attempt = 0
        while attempt < retries:
            for node_id, node_info in shard["nodes"].items():
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
                                shard["leader_id"] = response.leader_id
                                shard["leader_stub"] = leader_stub
                                logger.info(f"Found {shard_type} shard leader: Node {response.leader_id} at {leader_addr}")
                                return True
                        except Exception:
                            # The reported leader is dead, continue searching
                            continue
                except Exception:
                    continue
            
            # Wait for election to finish if leader was dead
            time.sleep(delay)
            attempt += 1
        
        logger.warning(f"No leader found for {shard_type} shard after retries.")
        return False
    
    def find_all_leaders(self):
        """Find leaders for both shards"""
        odd_success = self.find_leader("odd")
        even_success = self.find_leader("even")
        return odd_success and even_success
    
    def register_user(self, username, password):
        """Register a new user, randomly choosing even or odd shard"""
        # Randomly choose a shard
        shard_type = random.choice(["odd", "even"])
        
        # Find leader for that shard
        if not self.find_leader(shard_type):
            return {"success": False, "error": f"No leader available for {shard_type} shard"}
        
        content = pickle.dumps({"username": username, "password": password})
        
        try:
            shard = self.shards[shard_type]
            response = shard["leader_stub"].DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="register",
                    content=content,
                    commit_index=random.randint(1, 1000000)
                )
            )
            
            if response.success:
                return {"success": True, "message": f"User {username} registered successfully on {shard_type} shard"}
            else:
                return {"success": False, "error": "Registration failed"}
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            return {"success": False, "error": str(e)}
    
    def login_user(self, username, password):
        """Login a user by trying both shards"""
        # First check if user exists in either shard
        user_found = False
        user_shard = None
        
        # Try to find which shard the user is in
        if self.find_leader("even"):
            exists_result = self._check_user_exists("even", username)
            if exists_result["exists"]:
                user_found = True
                user_shard = "even"
        
        if not user_found and self.find_leader("odd"):
            exists_result = self._check_user_exists("odd", username)
            if exists_result["exists"]:
                user_found = True
                user_shard = "odd"
        
        # If user is found in a shard, try to login
        if user_found and user_shard:
            logger.info(f"Found user {username} in {user_shard} shard, attempting login")
            result = self._try_login(user_shard, username, password)
            return result
        
        return {"success": False, "error": "User not found in any shard"}
    
    def _check_user_exists(self, shard_type, username):
        """Check if a user exists in a specific shard"""
        logger.info(f"Checking if user '{username}' exists in {shard_type} shard")
        check_content = pickle.dumps({"username": username})
        
        try:
            shard = self.shards[shard_type]
            
            # Check if user exists in this shard
            user_check_response = shard["leader_stub"].DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="check_user_exists",
                    content=check_content,
                    commit_index=random.randint(1, 1000000)
                )
            )
            
            # Extract the result
            user_exists = False
            logger.info(f"Response from {shard_type} shard: success={user_check_response.success}, has_applied_data={hasattr(user_check_response, 'applied_data')}")
            
            if hasattr(user_check_response, 'applied_data') and user_check_response.applied_data:
                try:
                    user_exists = pickle.loads(user_check_response.applied_data)
                    logger.info(f"Unpickled result: {user_exists}")
                except Exception as e:
                    logger.error(f"Error unpickling result: {e}")
            
            result = {"exists": user_exists}
            logger.info(f"Final result for {shard_type} shard: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking if user exists in {shard_type} shard: {e}")
            return {"exists": False}
    
    def _try_login(self, shard_type, username, password):
        """Try to login on a specific shard"""
        login_content = pickle.dumps({"username": username, "password": password})
        
        try:
            shard = self.shards[shard_type]
            
            # Try to login
            login_response = shard["leader_stub"].DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="login",
                    content=login_content,
                    commit_index=random.randint(1, 1000000)
                )
            )
            
            if login_response.success:
                return {"success": True, "message": f"User {username} logged in successfully on {shard_type} shard"}
            else:
                return {"success": False, "error": "Invalid password"}
        except Exception as e:
            logger.error(f"Error during login on {shard_type} shard: {e}")
            return {"success": False, "error": str(e)}
    
    def list_all_users(self):
        """List all users from both shards"""
        all_users = []
        
        # Get users from odd shard
        if self.find_leader("odd"):
            odd_users = self._list_users("odd")
            if odd_users["success"]:
                all_users.extend(odd_users["users"])
        
        # Get users from even shard
        if self.find_leader("even"):
            even_users = self._list_users("even")
            if even_users["success"]:
                all_users.extend(even_users["users"])
        
        return {"success": True, "users": all_users, "count": len(all_users)}
    
    def _list_users(self, shard_type):
        """List users from a specific shard"""
        content = pickle.dumps({})
        
        try:
            shard = self.shards[shard_type]
            response = shard["leader_stub"].DBUpdate(
                raft_pb2.DBUpdateRequest(
                    action="list_users",
                    content=content,
                    commit_index=random.randint(1, 1000000)
                )
            )
            
            if response.success:
                return {"success": True, "users": pickle.loads(response.applied_data)}
            else:
                return {"success": False, "users": []}
        except Exception as e:
            logger.error(f"Error listing users on {shard_type} shard: {e}")
            return {"success": False, "users": []}


def main():
    parser = argparse.ArgumentParser(description="Sharded Raft Client")
    parser.add_argument("--action", choices=["register", "login", "list"], required=True, help="Action to perform")
    parser.add_argument("--username", help="Username for register/login")
    parser.add_argument("--password", help="Password for register/login")
    args = parser.parse_args()
    
    client = ShardedClient()
    
    if args.action == "register":
        if not args.username or not args.password:
            print("Error: Username and password required for registration")
            sys.exit(1)
        result = client.register_user(args.username, args.password)
    elif args.action == "login":
        if not args.username or not args.password:
            print("Error: Username and password required for login")
            sys.exit(1)
        result = client.login_user(args.username, args.password)
    elif args.action == "list":
        result = client.list_all_users()
    
    print(result)


if __name__ == "__main__":
    main()
