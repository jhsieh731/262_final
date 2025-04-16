# gRPC-based Raft Implementation

This implementation replaces the custom socket-based protocol in the original `raft_node.py` with gRPC for communication between replica servers.

## Components

1. **raft.proto**: Protocol buffer definition for the Raft service
2. **grpc_raft_node.py**: Main Raft node implementation with gRPC
3. **raft_client.py**: Client to interact with the Raft cluster
4. **database.py**: Simple database implementation for storing user data
5. **logger.py**: Logging utilities
6. **start_servers.py**: Helper script to start all three replica servers

## How to Run

### Prerequisites

Install the required dependencies:

```bash
pip install -r requirements.txt
```

### Starting the Servers

You can start all three replica servers at once using the helper script:

```bash
python start_servers.py
```

This will start three Raft nodes on the following ports:
- Node 1: localhost:50051
- Node 2: localhost:50052
- Node 3: localhost:50053

Alternatively, you can start each server individually in separate terminal windows:

```bash
# Terminal 1
python grpc_raft_node.py --id 1

# Terminal 2
python grpc_raft_node.py --id 2

# Terminal 3
python grpc_raft_node.py --id 3
```

### Using the Client

The client can interact with the Raft cluster to register and login users:

```bash
# Register a new user
python raft_client.py --action register --username user1 --password pass123

# Login a user
python raft_client.py --action login --username user1 --password pass123
```

## How It Works

### Leader Election

1. All nodes start as followers
2. If a follower doesn't receive a heartbeat from the leader within a timeout period, it becomes a candidate
3. The candidate requests votes from all other nodes
4. If a candidate receives votes from a majority of nodes, it becomes the leader
5. The leader sends regular heartbeats to maintain its leadership

### Log Replication

1. Client requests go to the leader
2. The leader appends the request to its log and replicates it to followers
3. Once a majority of followers have replicated the log entry, the leader applies it to its state machine (database)
4. The leader responds to the client

## Differences from Original Implementation

1. **Communication Protocol**: Uses gRPC instead of custom socket-based protocol
2. **Service Definition**: Clearly defined service interface in the proto file
3. **Concurrency**: Uses thread pools for handling concurrent requests
4. **Error Handling**: Improved error handling with timeouts and retries
5. **Client Interface**: Simplified client interface for interacting with the cluster

## Extending the Implementation

You can extend this implementation by:

1. Adding more database operations
2. Implementing log persistence
3. Adding more sophisticated leader election with log comparison
4. Implementing snapshot and log compaction
5. Adding security features like authentication and encryption
