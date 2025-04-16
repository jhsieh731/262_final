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

def print_table(cursor, table_name, out=None):
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        s = f"  Table: {table_name}\n    Columns: {columns}"
        print(s)
        if out: out.write(s + "\n")
        if rows:
            for row in rows:
                s = f"    {row}"
                print(s)
                if out: out.write(s + "\n")
        else:
            s = "    (empty)"
            print(s)
            if out: out.write(s + "\n")
    except Exception as e:
        s = f"  Error reading table {table_name}: {e}"
        print(s)
        if out: out.write(s + "\n")

def print_db_contents(db_file, out=None):
    s = f"\n=== {db_file} ==="
    print(s)
    if out: out.write(s + "\n")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        for table in ["users", "messages", "cart"]:
            print_table(cursor, table, out)
        conn.close()
    except Exception as e:
        s = f"  Error reading DB: {e}"
        print(s)
        if out: out.write(s + "\n")

def main():
    db_files = find_db_files()
    if not db_files:
        print("No .db files found.")
        return
    with open("db_dump.txt", "w") as out:
        for db_file in db_files:
            print_db_contents(db_file, out)

if __name__ == "__main__":
    main()
