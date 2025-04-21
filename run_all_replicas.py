import subprocess
import time
import os
import threading

def run_replicas(kind, base_port, count, db_prefix, script_name):
    processes = {}
    for i in range(count):
        port = base_port + i
        host = "localhost"
        peers = ",".join(f"{host}:{base_port + j}" for j in range(count) if j != i)
        db_file = f"{db_prefix}{i}.db"
        name = f"{kind}{i}"

        os.makedirs("logs", exist_ok=True)
        logfile = open(f"logs/{name}.log", "w")
        cmd = [
            "python", script_name,
            "--host", host,
            "--port", str(port),
            "--peers", peers,
            "--db", db_file
        ]
        print(f"[launch] {name} on {host}:{port}")
        proc = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT)
        processes[name] = (proc, logfile)
    return processes

def main():
    print("Spawning all replicas...\n")
    shard1 = run_replicas("s1r", 5000, 3, "shard1_replica", "shard_server.py")
    shard2 = run_replicas("s2r", 6000, 3, "shard2_replica", "shard_server.py")
    itinerary = run_replicas("it", 7100, 3, "itinerary_replica", "itinerary_server.py")

    all_procs = {**shard1, **shard2, **itinerary}

    print("\nInteractive commands:")
    print("- kill s1r0       (kill shard 1 replica 0)")
    print("- kill it2        (kill itinerary replica 2)")
    print("- list            (list live replicas)")
    print("- exit            (stop all)\n")

    def repl():
        while True:
            try:
                cmd = input("> ").strip()
                if cmd.startswith("kill "):
                    name = cmd.split(" ")[1]
                    if name in all_procs:
                        proc, log = all_procs[name]
                        proc.terminate()
                        print(f"[kill] {name} terminated")
                        del all_procs[name]
                    else:
                        print(f"[err] No such process: {name}")
                elif cmd == "list":
                    for name in all_procs:
                        proc, _ = all_procs[name]
                        status = "alive" if proc.poll() is None else "dead"
                        print(f"{name}: {status}")
                elif cmd == "exit":
                    break
                else:
                    print("[err] Unknown command.")
            except KeyboardInterrupt:
                break

        print("[shutdown] Killing all remaining processes...")
        for name, (proc, _) in all_procs.items():
            proc.terminate()
        print("[done]")

    repl()

if __name__ == "__main__":
    main()
