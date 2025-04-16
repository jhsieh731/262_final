import sqlite3
import uuid
import time
import random
import hashlib
import os

class ShardedDatabase:
    def __init__(self, shard_type, replica_id, db_dir="db"):
        """
        Initialize a sharded database (even or odd)
        
        Args:
            shard_type: "even" or "odd"
            replica_id: Replica number (1, 2, or 3)
            db_dir: Directory to store database files
        """
        self.shard_type = shard_type
        self.replica_id = replica_id
        
        # Ensure db directory exists
        os.makedirs(db_dir, exist_ok=True)
        
        # Create database file path
        db_file = f"{db_dir}/{shard_type}_shard_replica_{replica_id}.db"
        self.db_file = db_file
        
        # Connect to database
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Create tables
        self._create_tables()
        
        print(f"[{shard_type.upper()} SHARD] [REPLICA {replica_id}] Setting up database at: {db_file}")
    
    def _create_tables(self):
        """Create necessary database tables"""
        # Create users table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            last_login TEXT
        )
        ''')
        
        # Create messages table (for future expansion)
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            timestamp TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        # Create cart table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            username TEXT,
            item_name TEXT,
            quantity INTEGER
        )
        ''')
        self.conn.commit()
        print(f"[{self.shard_type.upper()} SHARD] [REPLICA {self.replica_id}] Database setup successful")
    
    def is_valid_for_shard(self, user_id):
        """Check if a user ID belongs to this shard"""
        if self.shard_type == "even":
            return user_id % 2 == 0
        else:  # odd shard
            return user_id % 2 == 1
    
    def generate_id(self):
        """Generate a new ID appropriate for this shard"""
        # Start with a random odd or even number based on shard
        base = random.randint(1, 1000000)
        if self.shard_type == "even":
            # Ensure even
            if base % 2 == 1:
                base += 1
        else:
            # Ensure odd
            if base % 2 == 0:
                base += 1
        return base
    
    def register(self, username, password):
        """Register a new user with appropriate ID for this shard"""
        try:
            # Hash the password
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            
            # Generate appropriate ID for this shard
            user_id = self.generate_id()
            
            # Insert user
            self.cursor.execute(
                "INSERT INTO users (id, username, password, last_login) VALUES (?, ?, ?, ?)",
                (user_id, username, hashed_password, time.strftime("%Y-%m-%d %H:%M:%S"))
            )
            self.conn.commit()
            return {"success": True, "user_id": user_id}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "Username already exists"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def login(self, username, password):
        """Login a user"""
        try:
            # Hash the password for comparison
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            
            # Find user
            self.cursor.execute(
                "SELECT id, password FROM users WHERE username = ?", 
                (username,)
            )
            result = self.cursor.fetchone()
            
            if result and result[1] == hashed_password:
                user_id = result[0]
                # Update last login
                self.cursor.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), user_id)
                )
                self.conn.commit()
                return {"success": True, "user_id": user_id}
            else:
                return {"success": False, "error": "Invalid username or password"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_user(self, user_id):
        """Get user by ID"""
        if not self.is_valid_for_shard(user_id):
            return {"success": False, "error": "User ID not valid for this shard"}
        
        try:
            self.cursor.execute("SELECT id, username, last_login FROM users WHERE id = ?", (user_id,))
            result = self.cursor.fetchone()
            
            if result:
                return {
                    "success": True,
                    "user": {
                        "id": result[0],
                        "username": result[1],
                        "last_login": result[2]
                    }
                }
            else:
                return {"success": False, "error": "User not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def list_users(self):
        """List all users in this shard"""
        try:
            self.cursor.execute("SELECT id, username, last_login FROM users")
            users = self.cursor.fetchall()
            
            result = []
            for user_id, username, last_login in users:
                result.append({
                    "id": user_id,
                    "username": username,
                    "last_login": last_login
                })
            
            return {"success": True, "users": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def delete_cart_for_user(self, username):
        """Delete all cart entries for a given username"""
        try:
            self.cursor.execute("DELETE FROM cart WHERE username = ?", (username,))
            self.conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_cart(self, username, items):
        """Save cart for a user (delete old, insert new)"""
        try:
            self.delete_cart_for_user(username)
            for item in items:
                self.cursor.execute(
                    "INSERT INTO cart (username, item_name, quantity) VALUES (?, ?, ?)",
                    (username, item["name"], item["quantity"])
                )
            self.conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def purchase_cart(self, username):
        """Delete all cart entries for a user after purchase"""
        try:
            # Simply reuse the delete_cart_for_user method
            return self.delete_cart_for_user(username)
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
