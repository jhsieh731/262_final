import subprocess
import os
import json
import time

def load_config():
    with open("config.json") as f:
        return json.load(f)

def run_load_balancers(config):
    processes = {}
    lb_configs = config["loadbalancer"]
    
    # Build complete peer list for Raft: static and dynamic, then join
    static_peers = ["10.0.0.144:8005", "10.0.0.144:8006", "10.0.0.144:8007"]
    dynamic_peers = [f"{lb['host']}:{lb['port']}" for lb in lb_configs]
    full_peers = static_peers + dynamic_peers
    peer_list = ",".join(full_peers)
    
    for i, lb in enumerate(lb_configs, start = 3):
        host, port, db_file = lb["host"], lb["port"], lb["db"]
        name = f"lb{i}"

        os.makedirs("logs", exist_ok=True)
        logfile = open(f"logs/{name}.log", "w")
        cmd = [
            "python", "load_balancer_server.py",
            "--host", host,
            "--port", str(port),
            "--peers", peer_list,
            "--db", db_file
        ]
        print(f"[launch] {name} on {host}:{port}")
        proc = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT)
        processes[name] = (proc, logfile)
        time.sleep(0.3) 
    
    return processes

def main():
    config = load_config()
    print("Spawning load balancer replicas...\n")
    
    load_balancers = run_load_balancers(config)

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