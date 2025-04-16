import subprocess
import time
import os
import signal
import sys

def start_server(node_id, port):
    """Start a Raft server with the given node ID and port"""
    cmd = f"python grpc_raft_node.py --id {node_id} --port {port}"
    process = subprocess.Popen(
        cmd, 
        shell=True, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid
    )
    return process

def main():
    # Configuration for 3 nodes
    nodes = [
        {"id": "1", "port": 50051},
        {"id": "2", "port": 50052},
        {"id": "3", "port": 50053}
    ]
    
    processes = []
    
    try:
        # Start all servers
        print("Starting Raft servers...")
        for node in nodes:
            process = start_server(node["id"], node["port"])
            processes.append(process)
            print(f"Started node {node['id']} on port {node['port']}")
            time.sleep(1)  # Give each server a moment to start
        
        print("\nAll servers started. Press Ctrl+C to stop all servers.")
        
        # Wait for user to terminate
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down all servers...")
    finally:
        # Terminate all processes
        for i, process in enumerate(processes):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                print(f"Stopped node {i+1}")
            except Exception as e:
                print(f"Error stopping node {i+1}: {e}")
        
        print("All servers stopped.")

if __name__ == "__main__":
    main()
