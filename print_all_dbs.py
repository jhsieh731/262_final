import os
import sqlite3

DB_DIRS = [".", "db"]  # Check both root and db/ subdir


def find_db_files():
    db_files = []
    for db_dir in DB_DIRS:
        if os.path.isdir(db_dir):
            for fname in os.listdir(db_dir):
                if fname.endswith(".db"):
                    db_files.append(os.path.join(db_dir, fname))
    return db_files

def print_table(cursor, table_name):
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        print(f"  Table: {table_name}")
        print(f"    Columns: {columns}")
        if rows:
            for row in rows:
                print(f"    {row}")
        else:
            print("    (empty)")
    except sqlite3.OperationalError:
        print(f"  Table: {table_name} (not found)")

def print_db_contents(db_file):
    print(f"\n=== {db_file} ===")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        for table in ["users", "messages", "cart"]:
            print_table(cursor, table)
        conn.close()
    except Exception as e:
        print(f"  Error reading DB: {e}")

def main():
    db_files = find_db_files()
    if not db_files:
        print("No .db files found.")
        return
    for db_file in db_files:
        print_db_contents(db_file)

if __name__ == "__main__":
    main()
