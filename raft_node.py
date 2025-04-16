import json
import time
import random
import threading
import socket
import selectors
import sys
from msg_server import Message
from database import MessageDatabase
from logger import set_logger

logger = set_logger("server", "server.log")


class RaftNode:
    def __init__(self, node_id, nodes, client_host, client_port):
        self.node_id = node_id
        self.nodes = nodes  # Store complete nodes config for lookup
        self.peers = [nodes[n] for n in nodes if int(n) != int(node_id)]
        self.peer_sockets = {}  # Mapping: (host, port) -> socket
        self.raft_host = nodes[node_id]["host"]
        self.raft_port = nodes[node_id]["port"]
        self.db = MessageDatabase(db_file=f"db_{node_id}.db")

        self.client_host = client_host
        self.client_port = client_port
        self.sel = selectors.DefaultSelector()

        self.current_term = 0
        self.voted_for = None
        self.last_applied = 0

        self.state = "follower"  # "follower", "candidate", "leader"
        self.leader_id = None
        self.election_timeout = random.uniform(3, 5)
        self.last_heartbeat = time.time()

        

        # Set up socket for receiving messages
        self.raft_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.raft_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.raft_socket.bind((self.raft_host, self.raft_port))
        self.raft_socket.listen(5)
        self.raft_socket_running = False


        # Start peer server
        self.start_peer_server()
        

    # --- Peer Communication Methods (without selectors) ---

    def start_peer_server(self):
        """Initialize the peer (Raft) server and accept connections in a separate thread."""
        self.raft_socket_running = True
        
        # Start listener thread for incoming connections
        listener_thread = threading.Thread(target=self._listen_for_connections)
        listener_thread.daemon = True
        listener_thread.start()
        logger.info(f"Raft server listening on {(self.raft_host, self.raft_port)}")

    
    def _listen_for_connections(self):
        """Listen for incoming connections from other machines"""
        while self.raft_socket_running:
            try:
                client_socket, _ = self.raft_socket.accept()
                handler = threading.Thread(target=self.handle_peer_connection, args=(client_socket,))
                handler.daemon = True
                handler.start()
            except Exception as e:
                if self.raft_socket_running:
                   logger.info(f"Error accepting connection: {e}")
    
    def handle_peer_connection(self, client_socket):
        """Handle messages from a connected client"""
        try:
            data = client_socket.recv(1024)
            if not data:
                logger.info("No data received; closing connection.")
                return
            message = json.loads(data.decode())
            logger.info(f"Decoded message: {message}")
            
            # Forward all messages (including "find_leader") to the common handler.
            self.process_peer_message(message)
                
        except Exception as e:
            logger.error(f"Error handling peer connection: {e}")
        finally:
            client_socket.close()

    # --- Client Communication (unchanged, but using threads) ---

    def initialize_client_server(self):
        """Initialize the client server and handle connections in a separate thread."""
        try:
            lsock_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lsock_client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                lsock_client.bind((self.client_host, self.client_port))
            except OSError as e:
                logger.error(f"Error binding to {self.client_host}:{self.client_port} - {e}")
                lsock_client.close()
                sys.exit(1)
            lsock_client.listen()
            logger.info(f"Client server listening on {(self.client_host, self.client_port)}")
            lsock_client.setblocking(False)
            self.sel.register(lsock_client, selectors.EVENT_READ, data=None)
            # threading.Thread(target=self.accept_client_connections, args=(lsock_client,), daemon=True).start()
            return lsock_client
        except Exception as e:
            logger.error(f"Error initializing client server: {e}")
            sys.exit(1)

    def accept_client_connections(self, lsock_client, accepted_versions, protocol):
        conn, addr = lsock_client.accept()
        logger.info(f"Accepted client connection from {addr}")
        conn.setblocking(False)
        message = Message(self.sel, conn, addr, accepted_versions, protocol, self.db, self.broadcast)
        self.sel.register(conn, selectors.EVENT_READ, data=message)


    # --- Main Run Loop ---

    def run(self, accepted_versions, protocol):
        """Run the Raft node for client actions (peer connections running in threads)"""
        # wait until all peers are up
        num_peers = 0
        while (num_peers != len(self.peers)):
            num_peers = 0
            for peer in self.peers[:]:
                if self.check_peer_status(peer):
                    num_peers += 1

        # Start election monitor thread (daemon so it exits with the main thread)
        self.election_thread = threading.Thread(target=self.monitor_election_timeout, daemon=True)
        self.election_thread.start()

         # Start peer status monitor thread
        self.peer_status_thread = threading.Thread(target=self.monitor_peer_status, daemon=True)
        self.peer_status_thread.start()

        self.last_heartbeat = time.time()

        try:
            while self.raft_socket_running:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    if key.data is None:
                        self.accept_client_connections(key.fileobj, accepted_versions, protocol)
                    else:
                        message = key.data
                        logger.info(f"Message: {message}")

                        try:
                            message.process_events(mask)
                        except Exception as e:
                            logger.error(f"Error processing events for {message.addr}: {e}")
                            message.close()
        except Exception as e:
            logger.info(f"\nError in server: {e}")
        except KeyboardInterrupt:
            logger.info("\nCaught keyboard interrupt, shutting down...")
        finally:
            logger.info("Closing all connections...")
            # Close all open sockets
            for key in list(self.sel.get_map().values()):
                self.sel.unregister(key.fileobj)
                key.fileobj.close()
            self.sel.close()
            self.raft_socket.close()
            self.raft_socket_running = False

    # --- Sending and Broadcasting ---
    def send_message(self, peer_host, peer_port, message):
        """Send a message to a peer machine"""
        client_socket = None
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((peer_host, peer_port))
            client_socket.sendall(json.dumps(message, ensure_ascii=False).encode('utf-8'))
            logger.info(f"Sending to client: {message}")
        except Exception as e:
            logger.info(f"Error sending message to port {peer_port}: {e}")
        finally:
            if client_socket:
                client_socket.close()

    def broadcast(self, message):
        """Send a message to all peers."""
        if message["type"] == "db_update":
            message["commit_index"] = self.last_applied + 1
            self.last_applied += 1
        for peer in self.peers:
            self.send_message(peer["host"], peer["port"], message)

    # --- Raft Protocol Methods ---

    def monitor_election_timeout(self):
        """Monitor if leader fails and start an election."""
        while True:
            time.sleep(1)
            logger.info(str(time.time() - self.last_heartbeat) + "; timeout: " + str(self.election_timeout))
            if self.state != "leader" and time.time() - self.last_heartbeat > self.election_timeout:
                self.election_timeout = random.uniform(3, 5)
                self.voted_for = None
                logger.info(f"Node {self.node_id} timed out. Starting election.")
                self.start_election()

    def start_election(self):
        """Start the leader election process."""
        self.state = "candidate"
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = 1  # Vote for self

        election_msg = {
            "type": "vote_request",
            "term": self.current_term,
            "candidate_id": self.node_id
        }
        self.broadcast(election_msg)

        start_time = time.time()
        while time.time() - start_time < 2:
            if self.votes_received >= 3:  # Majority votes
                self.state = "leader"
                self.leader_id = self.node_id
                logger.info(f"Node {self.node_id} is now the leader!")
                self.send_heartbeat()
                return
            time.sleep(0.5)
        
        self.state = "follower"
        self.last_heartbeat = time.time()

    def send_heartbeat(self):
        """Send heartbeat messages while the node is the leader."""
        while self.state == "leader":
            heartbeat_msg = {
                "type": "heartbeat",
                "term": self.current_term,
                "leader_id": self.node_id
            }
            self.broadcast(heartbeat_msg)
            time.sleep(1)

    def process_peer_message(self, message):
        """Process an incoming Raft message from a peer."""
        logger.info(f"Node {self.node_id} received message: {message}")
        if message["type"] == "heartbeat":
            # Reset voted_for if we see a new term
            if message["term"] > self.current_term:
                self.current_term = message["term"]
                self.voted_for = None
            
            self.last_heartbeat = time.time()
            self.leader_id = message["leader_id"]
            self.state = "follower"
        elif message["type"] == "find_leader":
            if self.state == "leader":
                response = {
                    "type": "find_leader_response",
                    "host": self.client_host,   # Use the client server's host
                    "port": self.client_port,   # Use the client server's port
                    "node_id": self.node_id
                }
            else:
                response = {
                    "type": "find_leader_response",
                    "host": None,
                    "port": None,
                    "node_id": self.leader_id
                }
            self.send_message(message["host"], message["port"], response)
        elif message["type"] == "vote_request":
            # Only vote if the candidate's term is at least as high as our current term
            # and we haven't voted yet in this term or we already voted for this candidate
            if (message["term"] > self.current_term) or \
                (message["term"] == self.current_term and 
                    (self.voted_for is None or self.voted_for == message["candidate_id"])):
                # Update our term if necessary
                if message["term"] > self.current_term:
                    self.current_term = message["term"]
                    self.voted_for = None  # Reset vote when moving to a new term
                
                # Now vote for the candidate
                self.voted_for = message["candidate_id"]
                vote_reply = {
                    "type": "vote_grant",
                    "term": self.current_term,
                    "vote_granted": True
                }
                # Look up candidate host and port from the configuration.
                candidate_info = self.nodes.get(str(message["candidate_id"]))
                if candidate_info:
                    self.send_message(candidate_info["host"], candidate_info["port"], vote_reply)
            else:
                # Send a negative vote reply
                vote_reply = {
                    "type": "vote_grant",
                    "term": self.current_term,
                    "vote_granted": False
                }
                candidate_info = self.nodes.get(str(message["candidate_id"]))
                # logger.info(f"voted no: term is {self.current_term} vs. proposed {message['term']}, voted_for is {self.voted_for}, candidate_id is {message['candidate_id']}")
                if candidate_info:
                    self.send_message(candidate_info["host"], candidate_info["port"], vote_reply) 
        elif message["type"] == "vote_grant":
            if message["vote_granted"]:
                self.votes_received += 1
        elif message["type"] == "db_update":
            commit_index = message["commit_index"]
            logger.info(f"commit_index: {commit_index}, last_applied: {self.last_applied}")
            if commit_index > self.last_applied:
                action = message.get("action", None)
                content = message.get("content", None)
                if action == "login":
                    username = content.get("username", None)
                    password = content.get("password", None)
                    addr = content.get("addr", None)
                    self.db.login(username, password, addr)
                    self.last_applied = commit_index
                elif action == "register":
                    username = content.get("username", None)
                    password = content.get("password", None)
                    addr = content.get("addr", None)
                    self.db.register(username, password, addr)
                    self.last_applied = commit_index
                elif action == "store_message":
                    sender_uuid = content.get("uuid", None)
                    recipient_uuid = content.get("recipient_uuid", None)
                    msg = content.get("message", None)
                    status = content.get("status", None)
                    timestamp = content.get("timestamp", None)
                    self.db.store_message(sender_uuid, recipient_uuid, msg, status, timestamp)
                    self.last_applied = commit_index
                elif action == "load_undelivered":
                    uuid = content.get("uuid", None)
                    num_messages = content.get("num_messages", None)
                    self.db.load_undelivered(uuid, num_messages)
                    self.last_applied = commit_index
                elif action == "delete_messages":
                    msg_ids = content.get("msg_ids", None)
                    self.db.delete_messages(msg_ids)
                    self.last_applied = commit_index
                elif action == "delete_user":
                    uuid = content.get("uuid", None)
                    self.db.delete_user(uuid)
                    self.last_applied = commit_index
                elif action == "delete_user_messages":
                    uuid = content.get("uuid", None)
                    self.db.delete_user_messages(uuid)
                    self.last_applied = commit_index


    def monitor_peer_status(self):
            """Monitor the status of peers and remove unresponsive peers."""
            while True:
                time.sleep(2)  # Check every 2 seconds
                for peer in self.peers[:]:
                    if not self.check_peer_status(peer):
                        logger.info(f"Peer {peer['host']}:{peer['port']} is unresponsive. Removing from peers.")
                        self.peers.remove(peer)

    def check_peer_status(self, peer):
        """Check if a peer is responsive."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # 1 second timeout
            sock.connect((peer["host"], peer["port"]))
            sock.close()
            return True
        except:
            return False

    def stop(self):
        """Perform any necessary cleanup before stopping."""
        sys.exit(0)