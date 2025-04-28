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

def run_load_balancers(config, full_config):
    processes = {}
    lb_configs = config["loadbalancer"]
    full_lb_configs = full_config["loadbalancer"]
    
    # Construct peer list for Raft
    peers = ",".join(f"{lb['host']}:{lb['port']}" for lb in full_lb_configs)
    # peer_list = ["10.250.25.48:8008", "10.250.25.48:8009"]
    # peer_list = ",".join(peer for peer in peer_list)
    # peer_list = self_peers + "," + peer_list
    
    for i, lb in enumerate(lb_configs):
        host, port, db_file = lb["host"], lb["port"], lb["db"]
        name = f"lb{i}"

        os.makedirs("logs", exist_ok=True)
        logfile = open(f"logs/{name}.log", "w")
        cmd = [
            "python", "load_balancer_server.py",
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
    print("Spawning load balancer replicas...\n")
    
    load_balancers = run_load_balancers(config, full_config)

    print("\nInteractive commands:")
    print("- kill lb0       (kill load balancer replica 0)")
    print("- list           (list live replicas)")
    print("- exit           (stop all)\n")

    def repl():
        while True:
            try:
                cmd = input("> ").strip()
                if cmd.startswith("kill "):
                    name = cmd.split(" ")[1]
                    if name in load_balancers:
                        proc, log = load_balancers[name]
                        proc.terminate()
                        print(f"[kill] {name} terminated")
                        del load_balancers[name]
                    else:
                        print(f"[err] No such process: {name}")
                elif cmd == "list":
                    for name in load_balancers:
                        proc, _ = load_balancers[name]
                        status = "alive" if proc.poll() is None else "dead"
                        print(f"{name}: {status}")
                elif cmd == "exit":
                    break
                else:
                    print("[err] Unknown command.")
            except KeyboardInterrupt:
                break

        print("[shutdown] Killing all remaining processes...")
        for name, (proc, _) in load_balancers.items():
            proc.terminate()
        print("[done]")

    repl()

if __name__ == "__main__":
    main()