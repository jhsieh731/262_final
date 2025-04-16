import sys
import os
import signal
import subprocess
import re

def find_node_pid(shard_type, node_id):
    """Find the PID of a sharded Raft node process with the given shard type and node ID."""
    # Use ps to list all python processes
    ps = subprocess.Popen(['ps', 'aux'], stdout=subprocess.PIPE)
    output = ps.communicate()[0].decode()
    
    # Look for the line with 'python' and '--shard <shard_type>' and '--id <node_id>' and 'sharded_raft_node.py'
    pattern = re.compile(rf"python[3]? .*sharded_raft_node\.py.*--shard {shard_type}.*--id {node_id}(\s|$)")
    alt_pattern = re.compile(rf"python[3]? .*sharded_raft_node\.py.*--id {node_id}.*--shard {shard_type}(\s|$)")
    
    for line in output.splitlines():
        if pattern.search(line) or alt_pattern.search(line):
            # PID is the second column
            pid = int(line.split()[1])
            return pid
    return None

def kill_node(shard_type, node_id, sig=signal.SIGTERM):
    """Kill a specific node in a specific shard."""
    pid = find_node_pid(shard_type, node_id)
    if pid:
        print(f"Killing {shard_type} shard node {node_id} (PID {pid}) with signal {sig}...")
        os.kill(pid, sig)
        print(f"Node killed.")
    else:
        print(f"Could not find process for {shard_type} shard node {node_id}.")

def main():
    if len(sys.argv) < 3:
        print("Usage: python kill_sharded_node.py <shard_type> <node_id> [SIGKILL]")
        print("  <shard_type>: 'odd' or 'even'")
        print("  <node_id>: '1', '2', or '3'")
        print("  [SIGKILL]: Optional, use SIGKILL instead of SIGTERM")
        sys.exit(1)
    
    shard_type = sys.argv[1]
    if shard_type not in ["odd", "even"]:
        print("Error: shard_type must be 'odd' or 'even'")
        sys.exit(1)
    
    node_id = sys.argv[2]
    if node_id not in ["1", "2", "3"]:
        print("Error: node_id must be '1', '2', or '3'")
        sys.exit(1)
    
    sig = signal.SIGKILL if (len(sys.argv) > 3 and sys.argv[3].upper() == "SIGKILL") else signal.SIGTERM
    kill_node(shard_type, node_id, sig)

if __name__ == "__main__":
    main()
