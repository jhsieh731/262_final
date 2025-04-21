import sqlite3
import os

REPLICAS = [
    "itinerary_replica0.db",
    "itinerary_replica1.db",
    "itinerary_replica2.db",
]

ITEMS = [("Apple", 100), ("Banana", 100), ("Carrot", 100)]

def reset_itinerary(db_file):
    if not os.path.exists(db_file):
        print(f"[skip] {db_file} does not exist")
        return

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS itinerary")
    cur.execute("""
        CREATE TABLE itinerary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            number INTEGER
        );
    """)

    for name, qty in ITEMS:
        cur.execute("INSERT INTO itinerary (name, number) VALUES (?, ?)", (name, qty))

    conn.commit()
    conn.close()
    print(f"[reset] {db_file} → 3 items inserted.")

if __name__ == "__main__":
    for db_file in REPLICAS:
        reset_itinerary(db_file)
