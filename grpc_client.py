import grpc
import hashlib
import random
import time

# Import the generated gRPC code
import shard_pb2
import shard_pb2_grpc

class ShardClient:
    """Client to interact with a specific shard service."""
    
    def __init__(self, shard_type):
        """
        Initialize a client for a specific shard.
        
        Args:
            shard_type (str): Either "odd" or "even".
        """
        self.shard_type = shard_type
        self.replicas = {}
        
        # Base port for odd shard: 50051, 50052, 50053
        # Base port for even shard: 50061, 50062, 50063
        base_port = 50050 if shard_type == "odd" else 50060
        
        # Initialize connections to all replicas
        for replica_id in range(1, 4):
            port = base_port + replica_id
            self.replicas[replica_id] = {
                "address": f"localhost:{port}",
                "channel": grpc.insecure_channel(f"localhost:{port}"),
                "stub": None,  # Will be created on demand
            }
        
        # Find the current leader
        self.leader_id = None
        self._find_leader()
    
    def _hash_password(self, password):
        """Hash a password using SHA-256."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _get_stub(self, replica_id):
        """Get or create the gRPC stub for a specific replica."""
        if self.replicas[replica_id]["stub"] is None:
            self.replicas[replica_id]["stub"] = shard_pb2_grpc.ShardServiceStub(
                self.replicas[replica_id]["channel"]
            )
        return self.replicas[replica_id]["stub"]
    
    def _find_leader(self):
        """Find the current leader of the shard."""
        for replica_id, replica in self.replicas.items():
            try:
                stub = self._get_stub(replica_id)
                response = stub.Heartbeat(
                    shard_pb2.HeartbeatRequest(replica_id=replica_id),
                    timeout=1
                )
                
                if response.is_leader:
                    self.leader_id = replica_id
                    print(f"[{self.shard_type.upper()} CLIENT] Found leader: Replica {replica_id}")
                    return
                elif response.leader_id > 0:
                    self.leader_id = response.leader_id
                    print(f"[{self.shard_type.upper()} CLIENT] Found leader from response: Replica {response.leader_id}")
                    return
            except grpc.RpcError:
                print(f"[{self.shard_type.upper()} CLIENT] Replica {replica_id} is unavailable")
        
        # If no leader found, try to elect a new one
        if self.leader_id is None:
            # Randomly choose a replica
            self.leader_id = random.randint(1, 3)
            print(f"[{self.shard_type.upper()} CLIENT] No leader found, assuming Replica {self.leader_id}")
    
    def find_user(self, username):
        """
        Find a user by username.
        
        Args:
            username (str): The username to find.
            
        Returns:
            tuple: (id, username, password_hash) if found, None otherwise.
        """
        # Ensure we have a leader
        if self.leader_id is None:
            self._find_leader()
            if self.leader_id is None:
                print(f"[{self.shard_type.upper()} CLIENT] No leader available, cannot find user")
                return None
        
        try:
            stub = self._get_stub(self.leader_id)
            response = stub.FindUser(shard_pb2.FindUserRequest(username=username))
            
            if response.found:
                return (response.user_id, response.username, response.password_hash)
            else:
                return None
        except grpc.RpcError as e:
            print(f"[{self.shard_type.upper()} CLIENT] RPC error when finding user: {e}")
            # Try to find a new leader and retry
            self._find_leader()
            if self.leader_id is None:
                return None
            
            # Retry with new leader
            try:
                stub = self._get_stub(self.leader_id)
                response = stub.FindUser(shard_pb2.FindUserRequest(username=username))
                
                if response.found:
                    return (response.user_id, response.username, response.password_hash)
                else:
                    return None
            except grpc.RpcError:
                return None
    
    def create_user(self, username, password):
        """
        Create a new user in the shard.
        
        Args:
            username (str): The username.
            password (str): The password.
            
        Returns:
            int: The new user ID if successful, None otherwise.
        """
        # Ensure we have a leader
        if self.leader_id is None:
            self._find_leader()
            if self.leader_id is None:
                print(f"[{self.shard_type.upper()} CLIENT] No leader available, cannot create user")
                return None
        
        # Hash the password
        password_hash = self._hash_password(password)
        
        try:
            stub = self._get_stub(self.leader_id)
            response = stub.CreateUser(
                shard_pb2.CreateUserRequest(
                    username=username,
                    password_hash=password_hash
                )
            )
            
            if response.success:
                return response.user_id
            else:
                print(f"[{self.shard_type.upper()} CLIENT] Failed to create user: {response.error_message}")
                return None
        except grpc.RpcError as e:
            print(f"[{self.shard_type.upper()} CLIENT] RPC error when creating user: {e}")
            # Try to find a new leader and retry
            self._find_leader()
            if self.leader_id is None:
                return None
            
            # Retry with new leader
            try:
                stub = self._get_stub(self.leader_id)
                response = stub.CreateUser(
                    shard_pb2.CreateUserRequest(
                        username=username,
                        password_hash=password_hash
                    )
                )
                
                if response.success:
                    return response.user_id
                else:
                    print(f"[{self.shard_type.upper()} CLIENT] Failed to create user: {response.error_message}")
                    return None
            except grpc.RpcError:
                return None
    
    def verify_login(self, username, password):
        """
        Verify login credentials.
        
        Args:
            username (str): The username.
            password (str): The password.
            
        Returns:
            int: The user ID if successful, None otherwise.
        """
        # Ensure we have a leader
        if self.leader_id is None:
            self._find_leader()
            if self.leader_id is None:
                print(f"[{self.shard_type.upper()} CLIENT] No leader available, cannot verify login")
                return None
        
        try:
            stub = self._get_stub(self.leader_id)
            response = stub.VerifyLogin(
                shard_pb2.VerifyLoginRequest(
                    username=username,
                    password=password
                )
            )
            
            if response.success:
                return response.user_id
            else:
                return None
        except grpc.RpcError:
            # Try to find a new leader and retry
            self._find_leader()
            if self.leader_id is None:
                return None
            
            # Retry with new leader
            try:
                stub = self._get_stub(self.leader_id)
                response = stub.VerifyLogin(
                    shard_pb2.VerifyLoginRequest(
                        username=username,
                        password=password
                    )
                )
                
                if response.success:
                    return response.user_id
                else:
                    return None
            except grpc.RpcError:
                return None
    
    def trigger_leader_election(self):
        """
        Trigger a leader election in the shard.
        
        Returns:
            int: The ID of the new leader if successful, None otherwise.
        """
        # Randomly select a new leader from the available replicas
        available_replicas = []
        
        for replica_id in range(1, 4):
            try:
                stub = self._get_stub(replica_id)
                response = stub.Heartbeat(
                    shard_pb2.HeartbeatRequest(replica_id=replica_id),
                    timeout=1
                )
                if response.alive:
                    available_replicas.append(replica_id)
            except grpc.RpcError:
                pass
        
        if not available_replicas:
            print(f"[{self.shard_type.upper()} CLIENT] No available replicas for leader election")
            return None
        
        # Select a new leader
        new_leader_id = random.choice(available_replicas)
        
        # Update all available replicas with the new leader
        for replica_id in available_replicas:
            try:
                stub = self._get_stub(replica_id)
                response = stub.UpdateLeader(
                    shard_pb2.UpdateLeaderRequest(
                        replica_id=new_leader_id,
                        is_leader=True
                    )
                )
                
                if not response.success:
                    print(f"[{self.shard_type.upper()} CLIENT] Failed to update replica {replica_id} with new leader")
            except grpc.RpcError:
                print(f"[{self.shard_type.upper()} CLIENT] Failed to contact replica {replica_id}")
        
        self.leader_id = new_leader_id
        print(f"[{self.shard_type.upper()} CLIENT] New leader elected: Replica {new_leader_id}")
        
        return new_leader_id

class HybridGrpcClient:
    """Client that communicates with both odd and even shards using gRPC."""
    
    def __init__(self):
        """Initialize the hybrid client with connections to both shards."""
        print("[HYBRID CLIENT] Initializing connections to both shards")
        self.odd_client = ShardClient("odd")
        self.even_client = ShardClient("even")
    
    def find_user(self, username):
        """
        Find a user by username in either shard.
        
        Args:
            username (str): The username to find.
            
        Returns:
            tuple: (user_id, username, password_hash, shard_type) if found, None otherwise.
        """
        print(f"[HYBRID CLIENT] Searching for user '{username}' in both shards")
        
        # Check odd shard first
        result = self.odd_client.find_user(username)
        if result:
            user_id, username, password_hash = result
            return (user_id, username, password_hash, "odd")
        
        # Then check even shard
        result = self.even_client.find_user(username)
        if result:
            user_id, username, password_hash = result
            return (user_id, username, password_hash, "even")
        
        return None
    
    def create_user(self, username, password):
        """
        Create a new user by randomly selecting a shard.
        
        Args:
            username (str): The username.
            password (str): The password.
            
        Returns:
            tuple: (user_id, shard_type) if successful, None otherwise.
        """
        # First check if user already exists
        if self.find_user(username):
            print(f"[HYBRID CLIENT] User '{username}' already exists, cannot create")
            return None
        
        # Randomly select a shard
        selected_shard = random.choice(["odd", "even"])
        print(f"[HYBRID CLIENT] Selected {selected_shard} shard for user '{username}'")
        
        if selected_shard == "odd":
            user_id = self.odd_client.create_user(username, password)
            if user_id:
                return (user_id, "odd")
        else:
            user_id = self.even_client.create_user(username, password)
            if user_id:
                return (user_id, "even")
        
        return None
    
    def verify_login(self, username, password):
        """
        Verify login credentials by checking both shards.
        
        Args:
            username (str): The username.
            password (str): The password.
            
        Returns:
            tuple: (user_id, shard_type) if successful, None otherwise.
        """
        print(f"[HYBRID CLIENT] Verifying login for user '{username}'")
        
        # Check if user exists and which shard they're in
        user_info = self.find_user(username)
        if not user_info:
            print(f"[HYBRID CLIENT] User '{username}' not found")
            return None
        
        # User found, verify password
        _, _, _, shard_type = user_info
        
        if shard_type == "odd":
            user_id = self.odd_client.verify_login(username, password)
            if user_id:
                return (user_id, "odd")
        else:
            user_id = self.even_client.verify_login(username, password)
            if user_id:
                return (user_id, "even")
        
        print(f"[HYBRID CLIENT] Password verification failed for user '{username}'")
        return None
    
    def trigger_leader_election(self, shard_type):
        """
        Trigger a leader election in the specified shard.
        
        Args:
            shard_type (str): Either "odd" or "even".
            
        Returns:
            int: The ID of the new leader if successful, None otherwise.
        """
        if shard_type == "odd":
            return self.odd_client.trigger_leader_election()
        else:
            return self.even_client.trigger_leader_election()
    
    def get_shard_info(self):
        """
        Get information about both shards.
        
        Returns:
            dict: Information about both shards.
        """
        return {
            "odd_shard": {
                "leader_id": self.odd_client.leader_id or -1,
                "replica_count": 3
            },
            "even_shard": {
                "leader_id": self.even_client.leader_id or -1,
                "replica_count": 3
            }
        }
