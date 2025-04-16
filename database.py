import sqlite3
import uuid
import time
import logging

class MessageDatabase:
    def __init__(self, db_file):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        
    def _create_tables(self):
        # Create users table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uuid TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            last_login TEXT
        )
        ''')
        
        # Create messages table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_uuid TEXT,
            recipient_uuid TEXT,
            message TEXT,
            status TEXT,
            timestamp TEXT,
            FOREIGN KEY (sender_uuid) REFERENCES users (uuid),
            FOREIGN KEY (recipient_uuid) REFERENCES users (uuid)
        )
        ''')
        self.conn.commit()
    
    def register(self, username, password, addr=None):
        try:
            user_uuid = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO users (uuid, username, password, last_login) VALUES (?, ?, ?, ?)",
                (user_uuid, username, password, time.strftime("%Y-%m-%d %H:%M:%S"))
            )
            self.conn.commit()
            return {"success": True, "uuid": user_uuid}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "Username already exists"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def login(self, username, password, addr=None):
        try:
            self.cursor.execute(
                "SELECT uuid, password FROM users WHERE username = ?", 
                (username,)
            )
            result = self.cursor.fetchone()
            
            if result and result[1] == password:
                user_uuid = result[0]
                self.cursor.execute(
                    "UPDATE users SET last_login = ? WHERE uuid = ?",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), user_uuid)
                )
                self.conn.commit()
                return {"success": True, "uuid": user_uuid}
            else:
                return {"success": False, "error": "Invalid username or password"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def store_message(self, sender_uuid, recipient_uuid, message, status="undelivered", timestamp=None):
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            self.cursor.execute(
                "INSERT INTO messages (sender_uuid, recipient_uuid, message, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                (sender_uuid, recipient_uuid, message, status, timestamp)
            )
            self.conn.commit()
            return {"success": True, "message_id": self.cursor.lastrowid}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def load_undelivered(self, uuid, num_messages=10):
        try:
            self.cursor.execute(
                "SELECT id, sender_uuid, message, timestamp FROM messages WHERE recipient_uuid = ? AND status = 'undelivered' ORDER BY timestamp DESC LIMIT ?",
                (uuid, num_messages)
            )
            messages = self.cursor.fetchall()
            result = []
            
            for msg_id, sender, content, timestamp in messages:
                result.append({
                    "id": msg_id,
                    "sender": sender,
                    "content": content,
                    "timestamp": timestamp
                })
                
            return {"success": True, "messages": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def delete_messages(self, msg_ids):
        if not msg_ids:
            return {"success": False, "error": "No message IDs provided"}
        
        try:
            placeholders = ', '.join(['?'] * len(msg_ids))
            self.cursor.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", msg_ids)
            self.conn.commit()
            return {"success": True, "count": self.cursor.rowcount}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def delete_user(self, uuid):
        try:
            self.cursor.execute("DELETE FROM users WHERE uuid = ?", (uuid,))
            self.conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def delete_user_messages(self, uuid):
        try:
            self.cursor.execute("DELETE FROM messages WHERE sender_uuid = ? OR recipient_uuid = ?", (uuid, uuid))
            self.conn.commit()
            return {"success": True, "count": self.cursor.rowcount}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def close(self):
        if self.conn:
            self.conn.close()
