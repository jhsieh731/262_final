import sqlite3
import os
import json


def load_config():
    with open("config.json") as f:
        return json.load(f)

config = load_config()
REPLICAS = [r["db"] for r in config["inventory"]]


ITEMS = [("Apple", 100), ("Banana", 100), ("Carrot", 100)]

def reset_inventory(db_file):
    # if not os.path.exists(db_file):
    #     print(f"[skip] {db_file} does not exist")
    #     return

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS inventory")
    cur.execute("""
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            number INTEGER
        );
    """)

    for name, qty in ITEMS:
        cur.execute("INSERT INTO inventory (name, number) VALUES (?, ?)", (name, qty))

    conn.commit()
    conn.close()
    print(f"[reset] {db_file} → 3 items inserted.")

if __name__ == "__main__":
    for db_file in REPLICAS:
        reset_inventory(db_file)
