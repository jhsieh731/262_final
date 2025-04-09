import subprocess
import time

def start_server(shard_type, replica_id, is_leader=False):
    """Start a replica server in a new process."""
    cmd = ["python3", "grpc_replica_server.py", shard_type, str(replica_id)]
    if is_leader:
        cmd.append("--leader")
    
    # Start the process
    process = subprocess.Popen(cmd)
    return process

def main():
    print("Starting all replica servers...")
    processes = []
    
    try:
        # Start odd shard replicas
        print("Starting odd shard replicas...")
        processes.append(start_server("odd", 1, True))  # Leader
        time.sleep(0.5)
        processes.append(start_server("odd", 2))
        time.sleep(0.5)
        processes.append(start_server("odd", 3))
        time.sleep(0.5)
        
        # Start even shard replicas
        print("Starting even shard replicas...")
        processes.append(start_server("even", 1, True))  # Leader
        time.sleep(0.5)
        processes.append(start_server("even", 2))
        time.sleep(0.5)
        processes.append(start_server("even", 3))
        
        print("\nAll servers started!")
        print("Press Ctrl+C to stop all servers\n")
        
        # Keep the script running until interrupted
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping all servers...")
        for process in processes:
            process.terminate()
        
        # Wait for all processes to terminate
        for process in processes:
            process.wait()
        
        print("All servers stopped")

if __name__ == "__main__":
    main()
