import tkinter as tk
from tkinter import messagebox, font
from grpc_client import HybridGrpcClient

class GrpcShardedLoginApp:
    def __init__(self, root):
        self.root = root
        self.root.title("gRPC Sharded Login System - CS 262 Final")
        self.root.geometry("600x400")
        self.root.configure(bg="#f0f0f0")
        
        # Initialize the gRPC client
        self.client = HybridGrpcClient()
        
        # Current user tracking
        self.current_user_id = None
        self.current_shard = None
        
        # Setup UI
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the initial login UI."""
        # Clear any existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Set up the login frame
        self.login_frame = tk.Frame(self.root, bg="#f0f0f0", padx=20, pady=20)
        self.login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # App title
        title_font = font.Font(family="Helvetica", size=18, weight="bold")
        title = tk.Label(self.login_frame, text="gRPC Sharded Database Login System", font=title_font, bg="#f0f0f0")
        title.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Architecture info
        info_font = font.Font(family="Helvetica", size=10, slant="italic")
        info_text = "User data is sharded across odd and even user IDs using gRPC communication"
        info = tk.Label(self.login_frame, text=info_text, font=info_font, bg="#f0f0f0")
        info.grid(row=1, column=0, columnspan=2, pady=(0, 20))
        
        # Username
        username_label = tk.Label(self.login_frame, text="Username:", bg="#f0f0f0")
        username_label.grid(row=2, column=0, sticky=tk.W, pady=5)
        self.username_entry = tk.Entry(self.login_frame, width=30)
        self.username_entry.grid(row=2, column=1, pady=5, sticky=tk.W)
        
        # Password
        password_label = tk.Label(self.login_frame, text="Password:", bg="#f0f0f0")
        password_label.grid(row=3, column=0, sticky=tk.W, pady=5)
        self.password_entry = tk.Entry(self.login_frame, width=30, show="*")
        self.password_entry.grid(row=3, column=1, pady=5, sticky=tk.W)
        
        # Login button
        login_button = tk.Button(self.login_frame, text="Login", command=self._handle_login, bg="#4CAF50", fg="black", padx=10)
        login_button.grid(row=4, column=0, pady=20)
        
        # Register button
        register_button = tk.Button(self.login_frame, text="Register", command=self._handle_register, bg="#2196F3", fg="black", padx=10)
        register_button.grid(row=4, column=1, pady=20)
    
    def _handle_login(self):
        """Handle login attempt."""
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required")
            return
        
        # Try to verify login
        result = self.client.verify_login(username, password)
        
        if result:
            user_id, shard_type = result
            self.current_user_id = user_id
            self.current_shard = shard_type
            messagebox.showinfo("Login Successful", f"Welcome back! User ID: {user_id} (from {shard_type} shard)")
            self._show_home_page()
        else:
            # Check if user exists but password is wrong
            user_info = self.client.find_user(username)
            
            if user_info:
                messagebox.showerror("Login Failed", "Invalid password")
            else:
                messagebox.showerror("Login Failed", "User not found")
    
    def _handle_register(self):
        """Handle registration attempt."""
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required")
            return
        
        # Try to create user
        result = self.client.create_user(username, password)
        
        if result:
            user_id, shard_type = result
            self.current_user_id = user_id
            self.current_shard = shard_type
            messagebox.showinfo("Account Created", 
                             f"New account created! User ID: {user_id} (on {shard_type} shard)")
            self._show_home_page()
        else:
            messagebox.showerror("Error", "Failed to create account. Username may already exist.")
    
    def _show_home_page(self):
        """Show the home page after successful login."""
        # Clear login frame
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Create home frame
        home_frame = tk.Frame(self.root, bg="#f0f0f0", padx=20, pady=20)
        home_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Welcome message
        welcome_font = font.Font(family="Helvetica", size=16, weight="bold")
        welcome = tk.Label(home_frame, 
                          text=f"Welcome User #{self.current_user_id}!", 
                          font=welcome_font, 
                          bg="#f0f0f0")
        welcome.pack(pady=(0, 10))
        
        # Shard info
        shard_font = font.Font(family="Helvetica", size=12)
        shard_info = tk.Label(home_frame, 
                             text=f"Your data is stored in the {self.current_shard.upper()} shard", 
                             font=shard_font, 
                             bg="#f0f0f0")
        shard_info.pack(pady=(0, 20))
        
        # Additional technical info
        tech_info_font = font.Font(family="Helvetica", size=10, slant="italic")
        
        tech_info1 = tk.Label(home_frame, 
                             text=f"Communication with the shard is handled via gRPC", 
                             font=tech_info_font, 
                             bg="#f0f0f0")
        tech_info1.pack(anchor=tk.W)
        
        tech_info2 = tk.Label(home_frame, 
                             text=f"User data is replicated across multiple replica servers", 
                             font=tech_info_font, 
                             bg="#f0f0f0")
        tech_info2.pack(anchor=tk.W)
        
        # Trigger election button
        election_button = tk.Button(home_frame, text=f"Trigger {self.current_shard} Shard Leader Election", 
                                 command=lambda: self._trigger_election(self.current_shard),
                                 bg="#FF9800", fg="black", padx=10)
        election_button.pack(pady=10)
        
        # Show election result label
        self.election_result_label = tk.Label(home_frame, text="", bg="#f0f0f0")
        self.election_result_label.pack(pady=5)
        
        # Logout button
        logout_button = tk.Button(home_frame, text="Logout", command=self._setup_ui, bg="#f44336", fg="black", padx=10)
        logout_button.pack(pady=20)
    
    def _trigger_election(self, shard_type):
        """Trigger a leader election in the specified shard."""
        new_leader_id = self.client.trigger_leader_election(shard_type)
        
        if new_leader_id:
            self.election_result_label.config(
                text=f"New leader elected for {shard_type} shard: Replica {new_leader_id}"
            )
        else:
            self.election_result_label.config(
                text=f"Failed to elect new leader for {shard_type} shard"
            )

if __name__ == "__main__":
    root = tk.Tk()
    app = GrpcShardedLoginApp(root)
    root.mainloop()
