import sys
import os
import signal
import subprocess
import re

def find_node_pid(node_id):
    """Find the PID of the Raft node process with the given ID."""
    # Use ps to list all python processes
    ps = subprocess.Popen(['ps', 'aux'], stdout=subprocess.PIPE)
    output = ps.communicate()[0].decode()
    
    # Look for the line with 'python' and '--id <node_id>' and 'grpc_raft_node.py'
    pattern = re.compile(rf"python[3]? .*grpc_raft_node\.py.*--id {node_id}(\s|$)")
    for line in output.splitlines():
        if pattern.search(line):
            # PID is the second column
            pid = int(line.split()[1])
            return pid
    return None

def kill_node(node_id, sig=signal.SIGTERM):
    pid = find_node_pid(node_id)
    if pid:
        print(f"Killing node {node_id} (PID {pid}) with signal {sig}...")
        os.kill(pid, sig)
        print(f"Node {node_id} killed.")
    else:
        print(f"Could not find process for node {node_id}.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python kill_node.py <node_id> [SIGKILL]")
        sys.exit(1)
    node_id = sys.argv[1]
    sig = signal.SIGKILL if (len(sys.argv) > 2 and sys.argv[2].upper() == "SIGKILL") else signal.SIGTERM
    kill_node(node_id, sig)

if __name__ == "__main__":
    main()
