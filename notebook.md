
# CS 262 Final Project

## System Design

### Database Tables

- users [id], sharded
- itinerary [id, name, num], global
- cart [userId, itineraryId, isDeleted, quantity], sharded

### Architecture

Client --> [Shard 1 (replicated), Shard 2 (replicated)] for users/cart --> itinerary (if any changes)

## Features

- Login/Create account (unique username only)
  - will require connecting to both shards and performing a join, then figuring out its own userid
  - if not in either shard, then randomly choose a shard and append a user (with odd or even id)
- Add/remove from persistent cart
  - send stub to correct shard to update cart
- Checkout cart
  - send stub to correct shard, which updates itinerary first, then sets "isDeleted" flag to true for all associated with userId

##

Next steps: just make the itinerary a Python list in the client, try to get gRPC up for replicated shards talking to the client and updating on new leader election
