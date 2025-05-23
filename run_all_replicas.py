import subprocess
import os
import json
import time

def load_config():
    with open("config.json") as f:
        return json.load(f)

def load_full_config():
    with open("fullconfig.json") as f:
        return json.load(f)

def run_replicas(kind, replicas, full_replicas, script_name):
    processes = {}
    for i, replica in enumerate(replicas):
        host, port, db_file = replica["host"], replica["port"], replica["db"]

        peers = ",".join(
            f"{peer['host']}:{peer['port']}"
            for peer in full_replicas if peer != replica
        )
        # if kind == "s1r":
        #     peers = ["10.250.213.42:5000","10.250.213.42:5001","10.250.213.42:5002"]
        # elif kind == "s2r":
        #     peers = ["10.250.213.42:6000","10.250.213.42:6001","10.250.213.42:6002"]
        # elif kind == "it":
        #     peers = ["10.250.213.42:7100","10.250.213.42:7101","10.250.213.42:7102"]
        
        # peers = ",".join(peers)
        # peers += "," + self_peers
        name = f"{kind}{i}"
        # print(peers)

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
        time.sleep(0.3) 
    return processes

def main():
    config = load_config()
    full_config = load_full_config()
    print("Spawning all replicas...\n")
    
    shard1 = run_replicas("s1r", config["shard1"], full_config["shard1"], "shard_server.py")
    shard2 = run_replicas("s2r", config["shard2"], full_config["shard2"], "shard_server.py")
    inventory = run_replicas("it", config["inventory"], full_config["inventory"], "inventory_server.py")

    all_procs = {**shard1, **shard2, **inventory}

    print("\nInteractive commands:")
    print("- kill s1r0       (kill shard 1 replica 0)")
    print("- kill it2        (kill inventory replica 2)")
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
