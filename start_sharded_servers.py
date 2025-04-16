import subprocess
import time
import os
import signal
import sys

def start_server(shard_type, node_id, port=None):
    """Start a sharded Raft server with the given shard type, node ID and optional port"""
    cmd = f"python sharded_raft_node.py --shard {shard_type} --id {node_id}"
    if port:
        cmd += f" --port {port}"
    
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
    # Configuration for 3 nodes in each shard
    odd_shard = [
        {"id": "1", "port": 50051},
        {"id": "2", "port": 50052},
        {"id": "3", "port": 50053}
    ]
    
    even_shard = [
        {"id": "1", "port": 50054},
        {"id": "2", "port": 50055},
        {"id": "3", "port": 50056}
    ]
    
    processes = []
    
    try:
        print("Starting all replica servers...")
        
        # Start odd shard replicas
        print("Starting odd shard replicas...")
        for node in odd_shard:
            process = start_server("odd", node["id"], node["port"])
            processes.append(process)
            time.sleep(1)  # Give each server a moment to start
        
        # Start even shard replicas
        print("Starting even shard replicas...")
        for node in even_shard:
            process = start_server("even", node["id"], node["port"])
            processes.append(process)
            time.sleep(1)  # Give each server a moment to start
        
        print("\nAll servers started!")
        print("Press Ctrl+C to stop all servers\n")
        
        # Wait for user to terminate
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping all servers...")
    finally:
        # Terminate all processes
        for process in processes:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except Exception as e:
                print(f"Error stopping server: {e}")
        
        print("All servers stopped")

if __name__ == "__main__":
    main()
