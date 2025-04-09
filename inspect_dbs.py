import sqlite3
import os
def print_database_contents(db_path):
    """Print all tables and their contents from a SQLite database."""
    print(f"\n=== Database: {os.path.basename(db_path)} ===")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            print("No tables found in this database.")
            return
        
        for table in tables:
            table_name = table[0]
            print(f"\nTable: {table_name}")
            print("-" * 50)
            
            # Get table columns
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            print("Columns:", ", ".join(column_names))
            
            # Get table data
            cursor.execute(f"SELECT * FROM {table_name};")
            rows = cursor.fetchall()
            
            if not rows:
                print("No data in this table.")
            else:
                for row in rows:
                    print(row)
            
            print("-" * 50)
        
        conn.close()
    except Exception as e:
        print(f"Error reading database: {e}")

def main():
    # Ensure db directory exists
    db_dir = os.path.join(os.path.dirname(__file__), 'db')
    if not os.path.exists(db_dir):
        print("No 'db' directory found. Run the application first to create databases.")
        return
    
    print("Inspecting all database files in:", db_dir)
    print("=" * 50)
    
    # Find all .db files
    db_files = [f for f in os.listdir(db_dir) if f.endswith('.db')]
    
    if not db_files:
        print("No database files found in 'db' directory.")
        return
    
    # Print each database
    for db_file in sorted(db_files):
        print_database_contents(os.path.join(db_dir, db_file))

if __name__ == "__main__":
    main()
