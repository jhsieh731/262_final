# CS262 Final Project: Sharded Shopping Cart

## Overview

This project implements a distributed shopping cart system using gRPC for backend communication, SQLite databases for persistence, and a Tkinter GUI for user interaction. The system is composed of:

- Two database shards, each with 3 replicated servers (total of 6 servers) handling user and cart information.
- A global itinerary service with 3 replicated servers that maintains available items.
- Leader-based replication and failover detection via heartbeats.

## Project Structure

```[markdown]
262_final/
├── client_gui.py               # Tkinter GUI client
├── run_all_replicas.py         # Script to launch all server replicas & kill servers at-will
├── config.json                 # Configuration file (servers, ports, DB locations)
├── shard_server.py             # Handles users and cart logic per shard
├── itinerary_server.py         # Global itinerary logic
├── reset_itinerary.py          # Helper script to reset itinerary dbs to {A: 100, B: 100, C:100}
├── proto/                      # Protobuf definitions
│   ├── user_cart.proto
│   └── itinerary.proto
├── db/                         # SQLite databases for each replica
├── logs/                       # Server logs
└── README.md                   # This file
└── requirements.txt            # Additional libraries required for project
```

## How to Run

Step 1: Run server replicas
Launch all server replicas (9 total):

```[bash]
python run_all_replicas.py
```

This starts:

- Shard 1: Ports 5000-5002
- Shard 2: Ports 6000-6002
- Itinerary servers: Ports 7100-7102

Step 2: Run GUI client
Launch the client interface:

```[bash]
python client_gui.py
```

## Core Features

- Sharded users/carts: Users are randomly assigned to one of two shards upon account creation. Cart data is sharded similarly.
- Global itinerary: Items available for purchase are managed globally by a separate replicated service.
- Leader-based replication: Each shard and the itinerary service maintain a single leader replica for consistency, and is monitored with heartbeats. On failure detection, the minimum lexical host:port is selected as the leader.
- Automatic leader detection: Clients use periodic heartbeats to detect and update leader information automatically.
- Failover: Clients reconnect if a server replica fails or if leadership changes occur. Clients have access to all server locations.
- Persistent SQLite storage: All data (users, carts, itinerary) persists in SQLite databases, synchronized via replication and messages to broadcast any writes from the leader.
- Tkinter GUI: Graphical interface allowing users to log in, add/remove cart items, and checkout.

## Design Decisions

- Replication strategy: we used leader-based replication, like in the past problem set. Each server type (shard/itinerary) elects a leader based on heartbeat responses and takes the minimum lexical host:port that's alive. Clients are aware of the current leaders by a heartbeat polling thread.
- Removal of stream-based updates: Initially, we implemented real-time streaming for itinerary updates but later switched to periodic polling to simplify client handling during leader changes.
- Configurable setup: All server configurations (hostnames, ports, database locations) are centralized in config.json to simplify deployment and testing.

## Notable Bugs Encountered and Solutions

1. Silent itinerary server failure due to lost leader heartbeat

    - Cause: The itinerary leader election timeout was too short, causing frequent leadership changes.
    - Solution: Increased LEADER_TIMEOUT from 5s to 10s, reducing false leader changes.

2. Client GUI not loading itinerary initially

    - Cause: GUI attempted to refresh itinerary before the GUI elements (Listbox) were created (i.e. on the first login screen).
    - Solution: Delayed starting the itinerary polling until after GUI initialization (post-login).

3. Listbox selection lost on itinerary polling

    - Cause: Periodic polling refreshed the GUI list, causing the user's selection to be cleared.
    - Solution: Implemented logic to save and restore the user's selection after each refresh (in self.selected_itinerary_index), and treat each appropriately on add/delete from cart.

4. Cart additions causing db UNIQUE constraint violation

    - Cause: Adding an item already in the cart caused a UNIQUE constraint violation.
    - Solution: Updated server logic to properly handle updating (accumulating quantity) existing cart items rather than always inserting new records.

5. No immediate itinerary update after checkout

    - Cause: After checkout, the itinerary GUI did not immediately reflect updated quantities.
    - Solution: Modified checkout logic in the GUI to explicitly fetch and refresh the itinerary immediately after checkout. [In addition to polling every few seconds.]

## Interactive Replica Management

The script run_all_replicas.py provides an interactive command-line interface to manage running replicas, allowing for some integration testing (& to make sure that leader election/client reconnection occurs correctly).

```[bash]
> kill s1r0      # Terminate shard 1, replica 0
> kill it2       # Terminate itinerary replica 2
> list           # List current replica statuses
> exit           # Shut down all replicas
```

## Logging

Logs for each server replica are stored in the logs/ directory.

