# CS262 Final Project: Sharded Shopping Cart

## Overview

This project implements a distributed shopping cart system using gRPC for backend communication, SQLite databases for persistence, and a Tkinter GUI for user interaction. The system is composed of:

- Two database shards, each with 3 replicated servers (total of 6 servers) handling user and cart information.
- A global inventory service with 3 replicated servers that maintains available items.
- Leader-based replication and failover detection via heartbeats.

## Project Structure

```[markdown]
262_final/
├── client_gui.py               # Tkinter GUI client
├── run_all_replicas.py         # Script to launch all server replicas & kill servers at-will
├── config.json                 # Configuration file (servers, ports, DB locations)
├── shard_server.py             # Handles users and cart logic per shard
├── inventory_server.py         # Global inventory logic
├── reset_inventory.py          # Helper script to reset inventory dbs to {A: 100, B: 100, C:100}
├── proto/                      # Protobuf definitions
│   ├── user_cart.proto
│   └── inventory.proto
├── db/                         # SQLite databases for each replica
├── logs/                       # Server logs
└── README.md                   # This file
└── requirements.txt            # Additional libraries required for project
```

## How to Run

Step 0: Make sure you have `db` and `logs` folders, as above. Make sure you have correctly installed libraries from `requirements.txt`:

```[bash]
pip install -r requirements.txt
```

Step 1: Run server replicas
Launch all server replicas (9 total):

```[bash]
python run_all_replicas.py
```

Step 2: Run GUI client
Launch the client interface:

```[bash]
python client_gui.py
```

If running on multiple machines, each server needs to be started individually, with a full list of peers (i.e. an inventory server receives peer inventory replica host:port addresses) passed to each.

Example Inventory: `python inventory_server.py --host localhost --port 7105 --peers localhost:7106,localhost:7107,localhost:7108,localhost:7109 --db db/inventory_replica0.db`

Example Shard 1: `python shard_server.py --host localhost --port 5005 --shard shard1 --peers localhost:5006,localhost:5007,localhost:5008,localhost:5009 --db db/shard1_replica0.db`

Example Shard 2: `python shard_server.py --host localhost --port 6005 --shard shard2 --peers localhost:6006,localhost:6007,localhost:6008,localhost:6009 --db db/shard2_replica0.db`

Example Load Balancer: `python loadbalancer_server.py --host localhost --port 8005 --peers localhost:8006,localhost:8007,localhost:8008,localhost:8009 --db db/loadbalancer_replica0.db`

## Core Features

- Sharded users/carts: Users are randomly assigned to one of two shards upon account creation. Cart data is sharded similarly.
- Global inventory: Items available for purchase are managed globally by a separate replicated service.
- Leader-based replication: Each shard and the inventory service maintain a single leader replica for consistency, and is monitored with heartbeats. On failure detection, the minimum lexical host:port is selected as the leader.
- Automatic leader detection: Clients use periodic heartbeats to detect and update leader information automatically.
- Failover: Clients reconnect if a server replica fails or if leadership changes occur. Clients have access to all server locations.
- Persistent SQLite storage: All data (users, carts, inventory) persists in SQLite databases, synchronized via replication and messages to broadcast any writes from the leader.
- Tkinter GUI: Graphical interface allowing users to log in, add/remove cart items, and checkout.

## Design Decisions

- Replication strategy: we used leader-based replication, like in the past problem set. Each server type (shard/inventory) elects a leader based on heartbeat responses and takes the minimum lexical host:port that's alive. Clients are aware of the current leaders by a heartbeat polling thread.
- Removal of stream-based updates: Initially, we implemented real-time streaming for inventory updates but later switched to periodic polling to simplify client handling during leader changes.
- Configurable setup: All server configurations (hostnames, ports, database locations) are centralized in config.json to simplify deployment and testing.

## Notable Bugs Encountered and Solutions

1. Silent inventory server failure due to lost leader heartbeat

    - Cause: The inventory leader election timeout was too short, causing frequent leadership changes.
    - Solution: Increased LEADER_TIMEOUT from 5s to 10s, reducing false leader changes.

2. Client GUI not loading inventory initially

    - Cause: GUI attempted to refresh inventory before the GUI elements (Listbox) were created (i.e. on the first login screen).
    - Solution: Delayed starting the inventory polling until after GUI initialization (post-login).

3. Listbox selection lost on inventory polling

    - Cause: Periodic polling refreshed the GUI list, causing the user's selection to be cleared.
    - Solution: Implemented logic to save and restore the user's selection after each refresh (in self.selected_inventory_index), and treat each appropriately on add/delete from cart.

4. Cart additions causing db UNIQUE constraint violation

    - Cause: Adding an item already in the cart caused a UNIQUE constraint violation.
    - Solution: Updated server logic to properly handle updating (accumulating quantity) existing cart items rather than always inserting new records.

5. No immediate inventory update after checkout

    - Cause: After checkout, the inventory GUI did not immediately reflect updated quantities.
    - Solution: Modified checkout logic in the GUI to explicitly fetch and refresh the inventory immediately after checkout. [In addition to polling every few seconds.]

## Interactive Replica Management

The script run_all_replicas.py provides an interactive command-line interface to manage running replicas, allowing for some integration testing (& to make sure that leader election/client reconnection occurs correctly).

```[bash]
> kill s1r0      # Terminate shard 1, replica 0
> kill it2       # Terminate inventory replica 2
> list           # List current replica statuses
> exit           # Shut down all replicas
```

## Logging

Logs for each server replica are stored in the logs/ directory.

