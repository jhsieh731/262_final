import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from sharded_client import ShardedClient

class LoginApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sharded Database Login System")
        self.root.geometry("500x400")
        self.root.resizable(False, False)
        
        # Configure style
        self.style = ttk.Style()
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TButton', background='#4CAF50', foreground='black', font=('Arial', 12))
        self.style.configure('TLabel', background='#f0f0f0', font=('Arial', 12))
        self.style.configure('TEntry', font=('Arial', 12))
        self.style.configure('Header.TLabel', font=('Arial', 18, 'bold'))
        self.style.configure('Status.TLabel', font=('Arial', 10), foreground='#555555')
        self.style.configure('Action.TButton', font=('Arial', 12))
        
        # Initialize client
        self.client = ShardedClient()
        
        # Create main frame
        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create header
        header_label = ttk.Label(self.main_frame, text="Sharded Database System", style='Header.TLabel')
        header_label.pack(pady=(0, 20))
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Create login tab
        self.login_frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(self.login_frame, text="Login")
        
        # Create register tab
        self.register_frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(self.register_frame, text="Register")
        
        # Setup login form
        self.setup_login_form()
        
        # Setup register form
        self.setup_register_form()
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        self.status_bar = ttk.Label(self.main_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        # Start connection status checker
        self.check_connection()
    
    def setup_login_form(self):
        # Username
        ttk.Label(self.login_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.login_username = ttk.Entry(self.login_frame, width=30)
        self.login_username.grid(row=0, column=1, sticky=tk.W, pady=5)
        
        # Password
        ttk.Label(self.login_frame, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.login_password = ttk.Entry(self.login_frame, width=30, show="*")
        self.login_password.grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # Login button
        login_button = ttk.Button(self.login_frame, text="Login", command=self.login)
        login_button.grid(row=2, column=1, sticky=tk.E, pady=20)
        
        # Bind Enter key to login
        self.login_username.bind("<Return>", lambda event: self.login_password.focus())
        self.login_password.bind("<Return>", lambda event: self.login())
        
        # Result label
        self.login_result_var = tk.StringVar()
        self.login_result = ttk.Label(self.login_frame, textvariable=self.login_result_var)
        self.login_result.grid(row=3, column=0, columnspan=2, pady=10)
    
    def setup_register_form(self):
        # Username
        ttk.Label(self.register_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.register_username = ttk.Entry(self.register_frame, width=30)
        self.register_username.grid(row=0, column=1, sticky=tk.W, pady=5)
        
        # Password
        ttk.Label(self.register_frame, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.register_password = ttk.Entry(self.register_frame, width=30, show="*")
        self.register_password.grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # Confirm Password
        ttk.Label(self.register_frame, text="Confirm Password:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.register_confirm = ttk.Entry(self.register_frame, width=30, show="*")
        self.register_confirm.grid(row=2, column=1, sticky=tk.W, pady=5)
        
        # Register button
        register_button = ttk.Button(self.register_frame, text="Register", command=self.register)
        register_button.grid(row=3, column=1, sticky=tk.E, pady=20)
        
        # Bind Enter key to register
        self.register_username.bind("<Return>", lambda event: self.register_password.focus())
        self.register_password.bind("<Return>", lambda event: self.register_confirm.focus())
        self.register_confirm.bind("<Return>", lambda event: self.register())
        
        # Result label
        self.register_result_var = tk.StringVar()
        self.register_result = ttk.Label(self.register_frame, textvariable=self.register_result_var)
        self.register_result.grid(row=4, column=0, columnspan=2, pady=10)
    
    def login(self):
        username = self.login_username.get()
        password = self.login_password.get()
        
        if not username or not password:
            self.login_result_var.set("Please enter both username and password")
            return
        
        self.status_var.set("Logging in...")
        self.login_result_var.set("Authenticating...")
        self.root.update()
        
        # Run login in a separate thread to avoid freezing the UI
        threading.Thread(target=self._login_thread, args=(username, password), daemon=True).start()
    
    def _login_thread(self, username, password):
        try:
            result = self.client.login_user(username, password)
            
            if result["success"]:
                self.root.after(0, lambda: self.login_result_var.set(f"Login successful!"))
                self.root.after(0, lambda: self.show_item_list(username))
            else:
                self.root.after(0, lambda: self.login_result_var.set(f"Login failed: {result.get('error', 'Unknown error')}"))
        except Exception as e:
            self.root.after(0, lambda: self.login_result_var.set(f"Error: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.status_var.set("Ready"))
            
    def show_item_list(self, username):
        # Create a new window for the item list
        item_window = tk.Toplevel(self.root)
        item_window.title(f"Item List - {username}")
        item_window.geometry("500x400")
        item_window.resizable(False, False)
        
        # Create main frame
        main_frame = ttk.Frame(item_window, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create header
        header_label = ttk.Label(main_frame, text=f"Welcome, {username}!", style='Header.TLabel')
        header_label.pack(pady=(0, 20))
        
        # Create item list frame
        item_frame = ttk.Frame(main_frame)
        item_frame.pack(fill=tk.X, expand=True)
        
        # Create column headers
        ttk.Label(item_frame, text="Item Name", font=('Arial', 12, 'bold')).grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        ttk.Label(item_frame, text="Quantity", font=('Arial', 12, 'bold')).grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # Create item rows with counters
        self.counters = []
        for i in range(5):
            # Item name
            ttk.Label(item_frame, text=f"Item {i+1}").grid(row=i+1, column=0, padx=10, pady=10, sticky=tk.W)
            
            # Counter frame
            counter_frame = ttk.Frame(item_frame)
            counter_frame.grid(row=i+1, column=1, padx=10, pady=10)
            
            # Configure counter button style
            self.style.configure('Counter.TButton', font=('Arial', 12, 'bold'), width=4)
            
            # Minus button
            minus_btn = ttk.Button(counter_frame, text="-", style='Counter.TButton',
                                command=lambda idx=i: self.decrement_counter(idx))
            minus_btn.pack(side=tk.LEFT, padx=5)
            
            # Counter value
            counter_var = tk.StringVar(value="0")
            self.counters.append(counter_var)
            counter_label = ttk.Label(counter_frame, textvariable=counter_var, width=4, 
                                   font=('Arial', 12), anchor='center')
            counter_label.pack(side=tk.LEFT, padx=10)
            
            # Plus button
            plus_btn = ttk.Button(counter_frame, text="+", style='Counter.TButton',
                               command=lambda idx=i: self.increment_counter(idx))
            plus_btn.pack(side=tk.LEFT, padx=5)
        
        # Add button frame for action buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20, fill=tk.X)
        
        # Configure button style (no width in style)
        self.style.configure('Action.TButton', font=('Arial', 12))
        
        # Add purchase button
        purchase_btn = tk.Button(button_frame, text="Purchase", bg="#4CAF50", fg="black",
                                font=("Arial", 12), command=lambda: self.purchase_items(username))
        purchase_btn.pack(side=tk.LEFT, padx=10, expand=True)
        
        # Add save button
        save_btn = tk.Button(button_frame, text="Save", bg="#2196F3", fg="black",
                            font=("Arial", 12), command=lambda: self.save_items(username, item_window))
        save_btn.pack(side=tk.LEFT, padx=10, expand=True)
        
        # Add logout button
        logout_btn = tk.Button(button_frame, text="Logout", bg="#f44336", fg="black",
                               font=("Arial", 12), command=lambda: self.logout(item_window))
        logout_btn.pack(side=tk.LEFT, padx=10, expand=True)
    
    def increment_counter(self, index):
        try:
            value = int(self.counters[index].get())
            self.counters[index].set(str(value + 1))
        except ValueError:
            self.counters[index].set("0")
    
    def decrement_counter(self, index):
        try:
            value = int(self.counters[index].get())
            if value > 0:
                self.counters[index].set(str(value - 1))
        except ValueError:
            self.counters[index].set("0")
    
    def purchase_items(self, username):
        """Process purchase and reset all counters to zero"""
        items = []
        total_items = 0
        
        # Collect items with quantity > 0
        for i, counter in enumerate(self.counters):
            quantity = int(counter.get())
            if quantity > 0:
                items.append({"name": f"Item {i+1}", "quantity": quantity})
                total_items += quantity
        
        if items:
            # Delete cart entries for this user
            result = self.client.purchase_cart(username)
            
            if result["success"]:
                # Show purchase confirmation
                message = f"Purchase successful! {username} bought {total_items} items:\n"
                for item in items:
                    message += f"- {item['name']}: {item['quantity']}\n"
                messagebox.showinfo("Purchase Complete", message)
                
                # Reset all counters to zero
                for counter in self.counters:
                    counter.set("0")
            else:
                messagebox.showerror("Purchase Error", f"Failed to process purchase: {result.get('error', 'Unknown error')}")
        else:
            messagebox.showinfo("No Items", "No items were selected for purchase.")
    
    def logout(self, window):
        """Close the item window and reset login form"""
        window.destroy()
        # Reset login form
        self.login_username.delete(0, tk.END)
        self.login_password.delete(0, tk.END)
        self.login_result_var.set("Logged out successfully")
        self.status_var.set("Ready")
        # Switch to login tab
        self.notebook.select(0)
    
    def save_items(self, username, window):
        """Save the current item selection to the backend cart table via the client."""
        items = []
        for i, counter in enumerate(self.counters):
            quantity = int(counter.get())
            if quantity > 0:
                items.append({"name": f"Item {i+1}", "quantity": quantity})
        
        # Call backend to save cart
        result = self.client.save_cart(username, items)
        if result["success"]:
            if items:
                message = f"Saved {len(items)} items for {username}:\n"
                for item in items:
                    message += f"- {item['name']}: {item['quantity']}\n"
                messagebox.showinfo("Items Saved", message)
            else:
                messagebox.showinfo("No Items", "No items were selected. Cart cleared.")
        else:
            messagebox.showerror("Save Error", f"Failed to save cart: {result.get('error', 'Unknown error')}")
    
    def register(self):
        username = self.register_username.get()
        password = self.register_password.get()
        confirm = self.register_confirm.get()
        
        if not username or not password or not confirm:
            self.register_result_var.set("Please fill in all fields")
            return
        
        if password != confirm:
            self.register_result_var.set("Passwords do not match")
            return
        
        self.status_var.set("Registering...")
        self.register_result_var.set("Creating account...")
        self.root.update()
        
        # Run registration in a separate thread to avoid freezing the UI
        threading.Thread(target=self._register_thread, args=(username, password), daemon=True).start()
    
    def _register_thread(self, username, password):
        try:
            result = self.client.register_user(username, password)
            
            if result["success"]:
                self.root.after(0, lambda: self.register_result_var.set(f"Registration successful!"))
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Account created for {username}!"))
                # Switch to login tab
                self.root.after(0, lambda: self.notebook.select(0))
                # Pre-fill login form
                self.root.after(0, lambda: self.login_username.delete(0, tk.END))
                self.root.after(0, lambda: self.login_username.insert(0, username))
                self.root.after(0, lambda: self.login_password.delete(0, tk.END))
                self.root.after(0, lambda: self.login_password.focus())
            else:
                self.root.after(0, lambda: self.register_result_var.set(f"Registration failed: {result.get('error', 'Unknown error')}"))
        except Exception as e:
            self.root.after(0, lambda: self.register_result_var.set(f"Error: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.status_var.set("Ready"))
    
    def check_connection(self):
        """Check connection to shards periodically"""
        threading.Thread(target=self._check_connection_thread, daemon=True).start()
    
    def _check_connection_thread(self):
        while True:
            try:
                # Try to find leaders for both shards
                even_leader = self.client.find_leader("even")
                odd_leader = self.client.find_leader("odd")
                
                if even_leader and odd_leader:
                    self.root.after(0, lambda: self.status_var.set("Connected to both shards"))
                elif even_leader:
                    self.root.after(0, lambda: self.status_var.set("Connected to even shard only"))
                elif odd_leader:
                    self.root.after(0, lambda: self.status_var.set("Connected to odd shard only"))
                else:
                    self.root.after(0, lambda: self.status_var.set("Not connected to any shard"))
            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Connection error: {str(e)}"))
            
            # Check again after 5 seconds
            time.sleep(5)


if __name__ == "__main__":
    root = tk.Tk()
    app = LoginApp(root)
    root.mainloop()
