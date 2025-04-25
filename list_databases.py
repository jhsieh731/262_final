#!/usr/bin/env python3
"""
Script to list all database files in the project
"""

import os
import sqlite3
import sys
from pathlib import Path

def list_databases(db_dir):
    """
    List all SQLite database files and print information about their tables
    """
    print(f"Scanning for databases in: {db_dir}")
    print("-" * 80)
    
    db_files = sorted([f for f in os.listdir(db_dir) if f.endswith('.db')])
    
    if not db_files:
        print("No database files found.")
        return
    
    print(f"Found {len(db_files)} database files:")
    
    for i, db_file in enumerate(db_files, 1):
        db_path = os.path.join(db_dir, db_file)
        print(f"\n{i}. {db_file} ({os.path.getsize(db_path) / 1024:.1f} KB)")
        
        try:
            # Connect to the database
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            if tables:
                print(f"   Tables ({len(tables)}):")
                for j, (table_name,) in enumerate(tables, 1):
                    # Get row count for each table
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row_count = cursor.fetchone()[0]
                    
                    # Get column info
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    print(f"   {j}. {table_name} ({row_count} rows)")
                    print(f"      Columns: {', '.join(column_names)}")
                    
                    # Show a sample of data if table has rows
                    if row_count > 0:
                        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                        sample_data = cursor.fetchall()
                        print(f"      Sample data (up to 3 rows):")
                        for row in sample_data:
                            print(f"        {row}")
            else:
                print("   No tables found in this database.")
                
            conn.close()
            
        except sqlite3.Error as e:
            print(f"   Error accessing database: {e}")
            
    print("\n" + "-" * 80)
    print(f"Summary: {len(db_files)} database files found in {db_dir}")

if __name__ == "__main__":
    import argparse, contextlib
    # Default db dir
    default_dir = os.path.join(Path(__file__).parent, "db")
    parser = argparse.ArgumentParser(description="List SQLite databases and write report to text file.")
    parser.add_argument("db_dir", nargs="?", default=default_dir, help="Directory containing .db files")
    parser.add_argument("-o","--output", default="db_report.txt", help="Output text file for report")
    args = parser.parse_args()
    if not os.path.isdir(args.db_dir):
        print(f"Error: Directory '{args.db_dir}' does not exist.")
        sys.exit(1)
    # Write report to file
    with open(args.output, "w") as out_f:
        with contextlib.redirect_stdout(out_f):
            list_databases(args.db_dir)
    print(f"Report written to {args.output}")
