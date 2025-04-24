import json
import sqlite3
import os

def print_db_contents():
    # Create db directory if it doesn't exist
    os.makedirs('db', exist_ok=True)
    
    # Load the config file
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Go through all sections in the config
    for section_name, servers in config.items():
        print(f"\n{'='*50}")
        print(f"SECTION: {section_name}")
        print(f"{'='*50}")
        
        # Go through each server in the section
        for server in servers:
            db_path = server['db']
            print(f"\nDatabase: {db_path}")
            print(f"{'-'*50}")
            
            # Check if the database file exists
            if not os.path.exists(db_path):
                print(f"Database file does not exist. Creating an empty database.")
                # Create the directory if it doesn't exist
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
                # Create an empty database
                sqlite3.connect(db_path).close()
            
            try:
                # Connect to the database
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Get list of tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                
                if not tables:
                    print("No tables found in database.")
                else:
                    # Print contents of each table
                    for table in tables:
                        table_name = table[0]
                        print(f"\nTable: {table_name}")
                        
                        # Get column names
                        cursor.execute(f"PRAGMA table_info({table_name})")
                        columns = [col[1] for col in cursor.fetchall()]
                        print(f"Columns: {', '.join(columns)}")
                        
                        # Get all rows
                        cursor.execute(f"SELECT * FROM {table_name}")
                        rows = cursor.fetchall()
                        
                        if not rows:
                            print("No data in table.")
                        else:
                            print(f"Row count: {len(rows)}")
                            print("\nData:")
                            for row in rows:
                                print(row)
                
                conn.close()
            
            except sqlite3.Error as e:
                print(f"Error accessing database: {e}")
    
if __name__ == "__main__":
    print_db_contents()