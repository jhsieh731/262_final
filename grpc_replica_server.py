import grpc
import sqlite3
import os
import time
import threading
import hashlib
import random
from concurrent import futures

# Import the generated gRPC code
import shard_pb2
import shard_pb2_grpc

class ShardServicer(shard_pb2_grpc.ShardServiceServicer):
    """Implements the ShardService gRPC service."""
    
    def __init__(self, shard_type, replica_id, initial_leader=False):
        """
        Initialize a shard servicer.
        
        Args:
            shard_type (str): Either "odd" or "even".
            replica_id (int): ID of this replica (1, 2, or 3).
            initial_leader (bool): Whether this replica is initially the leader.
        """
        self.shard_type = shard_type
        self.replica_id = replica_id
        self.is_leader = initial_leader
        self.leader_id = replica_id if initial_leader else None
        
        # Database path
        os.makedirs('db', exist_ok=True)
        self.db_path = f'db/{shard_type}_shard_replica_{replica_id}.db'
        
        # Initialize database
        self._setup_database()
        
        print(f"[{shard_type.upper()} SHARD] [REPLICA {replica_id}] Started")
        if self.is_leader:
            print(f"[{shard_type.upper()} SHARD] [REPLICA {replica_id}] I am the leader")
    
    def _setup_database(self):
        """Set up the database for this replica."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def _hash_password(self, password):
        """Hash a password using SHA-256."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def FindUser(self, request, context):
        """
        Find a user by username.
        
        Implementation of the FindUser RPC method.
        """
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Searching for user: {request.username}")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (request.username,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Found user: {request.username}")
                return shard_pb2.FindUserResponse(
                    found=True,
                    user_id=result[0],
                    username=result[1],
                    password_hash=result[2]
                )
            else:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] User not found: {request.username}")
                return shard_pb2.FindUserResponse(found=False)
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error finding user: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error finding user: {e}")
            return shard_pb2.FindUserResponse(found=False)
    
    def CreateUser(self, request, context):
        """
        Create a new user.
        
        Implementation of the CreateUser RPC method.
        """
        if not self.is_leader:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Not a leader, cannot create user")
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("Not the leader, cannot create user")
            return shard_pb2.CreateUserResponse(success=False, error_message="Not the leader, cannot create user")
        
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Creating user: {request.username}")
        
        try:
            # Get next available ID
            highest_id = self._get_highest_user_id()
            
            if self.shard_type == "odd":
                new_id = 1 if highest_id == 0 else highest_id + 2
            else:  # even
                new_id = 2 if highest_id == 0 else highest_id + 2
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if username already exists
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (request.username,))
            if cursor.fetchone()[0] > 0:
                conn.close()
                return shard_pb2.CreateUserResponse(success=False, error_message="Username already exists")
            
            # Insert new user
            cursor.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (new_id, request.username, request.password_hash)
            )
            
            conn.commit()
            conn.close()
            
            # Replicate to other replicas
            self._replicate_user_to_other_replicas(new_id, request.username, request.password_hash)
            
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Created user: {request.username} (ID: {new_id})")
            return shard_pb2.CreateUserResponse(success=True, user_id=new_id)
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error creating user: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error creating user: {e}")
            return shard_pb2.CreateUserResponse(success=False, error_message=str(e))
    
    def VerifyLogin(self, request, context):
        """
        Verify login credentials.
        
        Implementation of the VerifyLogin RPC method.
        """
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Verifying login for: {request.username}")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (request.username,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result and result[1] == self._hash_password(request.password):
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Login verified for: {request.username}")
                return shard_pb2.VerifyLoginResponse(success=True, user_id=result[0])
            else:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Login failed for: {request.username}")
                return shard_pb2.VerifyLoginResponse(success=False)
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error verifying login: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error verifying login: {e}")
            return shard_pb2.VerifyLoginResponse(success=False)
    
    def GetHighestUserId(self, request, context):
        """
        Get the highest user ID in this shard.
        
        Implementation of the GetHighestUserId RPC method.
        """
        highest_id = self._get_highest_user_id()
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Highest user ID: {highest_id}")
        return shard_pb2.GetHighestUserIdResponse(highest_id=highest_id)
    
    def UpdateLeader(self, request, context):
        """
        Update the leader status.
        
        Implementation of the UpdateLeader RPC method.
        """
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Update leader: Replica {request.replica_id} is {'leader' if request.is_leader else 'not leader'}")
        
        if request.is_leader:
            # Update leader status
            self.is_leader = (request.replica_id == self.replica_id)
            self.leader_id = request.replica_id
            
            if self.is_leader:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] I am now the leader")
            else:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Replica {request.replica_id} is now the leader")
        
        return shard_pb2.UpdateLeaderResponse(success=True, current_leader_id=self.leader_id if self.leader_id else -1)
    
    def Heartbeat(self, request, context):
        """
        Handle heartbeat requests.
        
        Implementation of the Heartbeat RPC method.
        """
        return shard_pb2.HeartbeatResponse(
            alive=True,
            is_leader=self.is_leader,
            leader_id=self.leader_id if self.leader_id else -1
        )
        
    def DirectInsert(self, request, context):
        """
        Directly insert a user into this replica's database.
        Used for replication between replicas.
        
        Implementation of the DirectInsert RPC method.
        """
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Received replication request for user: {request.username}")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if user already exists
            cursor.execute("SELECT COUNT(*) FROM users WHERE id = ?", (request.user_id,))
            if cursor.fetchone()[0] > 0:
                conn.close()
                return shard_pb2.DirectInsertResponse(success=True)  # Already exists, consider it a success
            
            # Insert the user
            cursor.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (request.user_id, request.username, request.password_hash)
            )
            
            conn.commit()
            conn.close()
            
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Replicated user: {request.username} (ID: {request.user_id})")
            return shard_pb2.DirectInsertResponse(success=True)
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error replicating user: {e}")
            return shard_pb2.DirectInsertResponse(success=False, error_message=str(e))
    
    def _replicate_user_to_other_replicas(self, user_id, username, password_hash):
        """
        Replicate a new user to all other replicas in the shard.
        
        Args:
            user_id (int): The user ID.
            username (str): The username.
            password_hash (str): The hashed password.
        """
        # Base port for odd shard: 50051, 50052, 50053
        # Base port for even shard: 50061, 50062, 50063
        base_port = 50050 if self.shard_type == "odd" else 50060
        
        # Connect to all other replicas and replicate the user
        for replica_id in range(1, 4):
            # Skip self
            if replica_id == self.replica_id:
                continue
                
            try:
                # Create a channel and stub for the replica
                port = base_port + replica_id
                channel = grpc.insecure_channel(f"localhost:{port}")
                stub = shard_pb2_grpc.ShardServiceStub(channel)
                
                # Create a direct insert request (bypass leader check)
                request = shard_pb2.DirectInsertRequest(
                    user_id=user_id,
                    username=username,
                    password_hash=password_hash
                )
                
                # Call the DirectInsert method
                response = stub.DirectInsert(request, timeout=1)
                
                if response.success:
                    print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Replicated user {username} to replica {replica_id}")
                else:
                    print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Failed to replicate user {username} to replica {replica_id}: {response.error_message}")
                
                channel.close()
            except Exception as e:
                print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error replicating to replica {replica_id}: {e}")
    
    def _get_highest_user_id(self):
        """
        Get the highest user ID in the database.
        
        Returns:
            int: The highest user ID, or 0 if no users exist.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT MAX(id) FROM users")
            max_id = cursor.fetchone()[0]
            
            conn.close()
            
            return max_id if max_id is not None else 0
        except Exception as e:
            print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Error getting highest user ID: {e}")
            return 0

def serve(shard_type, replica_id, is_leader=False, port=None):
    """
    Start a gRPC server for a shard replica.
    
    Args:
        shard_type (str): Either "odd" or "even".
        replica_id (int): ID of the replica (1, 2, or 3).
        is_leader (bool): Whether this replica is initially the leader.
        port (int): Port to listen on. If None, a default port will be used.
    """
    # Calculate port if not provided
    if port is None:
        # Base port for odd shard: 50051, 50052, 50053
        # Base port for even shard: 50061, 50062, 50063
        base_port = 50050 if shard_type == "odd" else 50060
        port = base_port + replica_id
    
    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    shard_pb2_grpc.add_ShardServiceServicer_to_server(
        ShardServicer(shard_type, replica_id, is_leader), server
    )
    server.add_insecure_port(f'[::]:{port}')
    
    # Start server
    server.start()
    print(f"[{shard_type.upper()} SHARD] [REPLICA {replica_id}] Server started on port {port}")
    
    try:
        while True:
            time.sleep(86400)  # Sleep for a day
    except KeyboardInterrupt:
        server.stop(0)
        print(f"[{shard_type.upper()} SHARD] [REPLICA {replica_id}] Server stopped")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Start a shard replica server")
    parser.add_argument("shard_type", choices=["odd", "even"], help="Type of shard (odd or even)")
    parser.add_argument("replica_id", type=int, choices=[1, 2, 3], help="Replica ID (1, 2, or 3)")
    parser.add_argument("--leader", action="store_true", help="Set this replica as the initial leader")
    parser.add_argument("--port", type=int, help="Port to listen on")
    
    args = parser.parse_args()
    
    serve(args.shard_type, args.replica_id, args.leader, args.port)
