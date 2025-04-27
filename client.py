import tkinter as tk
from tkinter import ttk, messagebox
import grpc
import threading
import time
import random
import logging 
import json
from concurrent.futures import ThreadPoolExecutor
import hashlib

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "proto")))
from proto import user_cart_pb2, user_cart_pb2_grpc
from proto import inventory_pb2, inventory_pb2_grpc
from proto import load_balancer_pb2, load_balancer_pb2_grpc

def load_config():
    with open("config.json") as f:
        return json.load(f)

config = load_config()

# Load balancer replicas from config
LOAD_BALANCER_REPLICAS = [(r["host"], r["port"]) for r in config["loadbalancer"]] + [("10.0.0.188", 8008), ("10.0.0.188", 8009)]

POLL_INTERVAL = 5  # seconds

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
file_handler = logging.FileHandler('logs/client_app.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def create_stub_list(replicas, stub_class):
    return [(addr, stub_class(grpc.insecure_channel(f"{addr[0]}:{addr[1]}"))) for addr in replicas]

class ClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Shopping Cart")
        self.root.geometry("600x500")
        
        # Configure style
        self.style = ttk.Style()
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TButton', background='#4CAF50', foreground='black', font=('Arial', 12))
        self.style.configure('TLabel', background='#f0f0f0', font=('Arial', 12))
        self.style.configure('TEntry', font=('Arial', 12))
        self.style.configure('Header.TLabel', font=('Arial', 18, 'bold'))
        self.style.configure('Status.TLabel', font=('Arial', 10), foreground='#555555')
        self.style.configure('Action.TButton', font=('Arial', 12))

        # State variables
        self.user_id = None
        self.current_username = ""
        self.cart = {}
        self.inventory_items = []
        self.selected_inventory_index = None

        # Leader tracking
        self.load_balancer_leader = None

        # Thread pool for async operations
        self.thread_pool = ThreadPoolExecutor(max_workers=5)

        # Create stubs for gRPC services
        self.lb_stubs = create_stub_list(LOAD_BALANCER_REPLICAS, load_balancer_pb2_grpc.LoadBalancerServiceStub)

        # Main container
        self.main_container = ttk.Frame(self.root, style='TFrame')
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Header section
        self.header_frame = ttk.Frame(self.main_container, style='TFrame')
        self.header_frame.pack(fill=tk.X, pady=15, padx=20)
        
        self.header_label = ttk.Label(self.header_frame, 
                                     text="Shopping Cart", 
                                     style='Header.TLabel')
        self.header_label.pack(side=tk.LEFT)
        
        # Status section
        self.status_var = tk.StringVar()
        self.status_var.set("Finding load balancer...")
        self.status_bar = ttk.Label(self.main_container, 
                                   textvariable=self.status_var, 
                                   style='Status.TLabel')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)

        # Create frames for different views
        self.login_frame = self.create_login_frame()
        self.main_frame = self.create_main_frame()
        
        # Start with login frame visible
        self.login_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Start leader monitoring
        self._start_heartbeat_thread()

    def _start_heartbeat_thread(self):
        """Start background thread to monitor load balancer leaders"""
        def monitor():
            while True:
                try:
                    leader = None
                    for (host, port), stub in self.lb_stubs:
                        try:
                            heartbeat_request = load_balancer_pb2.HeartbeatRequest(host=host, port=port)
                            response = stub.Heartbeat(heartbeat_request, timeout=1.0)
                            if response.is_leader:
                                leader = (host, port)
                                self.root.after(0, lambda: self.status_var.set(f"Connected to load balancer {host}:{port}"))
                                break
                        except grpc.RpcError as e:
                            if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                                leader_info = e.details().split("leader:")
                                if len(leader_info) > 1:
                                    leader_addr = leader_info[1].strip()
                                    try:
                                        leader_host, leader_port = leader_addr.split(":")
                                        leader = (leader_host, int(leader_port))
                                        break
                                    except ValueError:
                                        pass
                    
                    # Update the leader if we found one
                    if leader:
                        if self.load_balancer_leader != leader:
                            logger.info(f"Load balancer leader changed to {leader}")
                        self.load_balancer_leader = leader
                    else:
                        self.root.after(0, lambda: self.status_var.set(f"No load balancer found"))
                        
                except Exception as e:
                    logger.error(f"Error in load balancer monitoring: {e}")
                    
                time.sleep(2)
                
        threading.Thread(target=monitor, daemon=True).start()

        
    # The rest of your UI code stays mostly the same
    # Only changes are in the methods that perform gRPC calls

    def get_lb_stub(self):
        """Get a stub for the current load balancer leader"""
        if self.load_balancer_leader:
            return next((stub for (h, p), stub in self.lb_stubs if (h, p) == self.load_balancer_leader), None)
        return None

    def login(self):
        """Login using background thread"""
        logger.info("Login button clicked")
        username = self.username_entry.get().strip()
        password = self.password_entry.get()

        if not username or not password:
            messagebox.showerror("Error", "Username and password cannot be empty")
            return
        
        hashed_password = self.hash_password(password)
        logger.info(f"Logging in user {username} with hashed password")

        self.login_result_var.set("Logging in...")
        
        stub = self.get_lb_stub()
        logger.info(f"Using load balancer stub: {stub}")
        if not stub:
            messagebox.showerror("Error", "No load balancer available")
            self.login_result_var.set("No load balancer available")
            return

        def on_success(response):
            if response.success:
                self.user_id = response.user_id
                self.current_username = username
                logger.info(f"User {username} logged in with ID {self.user_id}")
                self.login_result_var.set("Login successful")
                self.load_cart()
                self.switch_to_main()
            else:
                self.login_result_var.set("Invalid username or password")
                messagebox.showerror("Error", "Invalid username or password")

        def make_rpc():
            # Use the load balancer's imported LoginRequest
            try:
                logger.info(f"Attempting login for {username}")
                login_request = user_cart_pb2.LoginRequest(username=username, password=hashed_password)
                return stub.Login(login_request)
            except Exception as e:
                logger.error(f"Login RPC error: {e}")
                return None

        self.threaded_rpc("Login", make_rpc, on_success, self.login)

    def create_account(self):
        """Create account using background thread"""
        username = self.register_username.get().strip()
        password = self.register_password.get()
        confirm_password = self.register_confirm_password.get()

        if not username or not password or not confirm_password:
            messagebox.showerror("Error", "Fields cannot be empty")
            return
        
        if password != confirm_password:
            self.register_result_var.set("Passwords do not match")
            messagebox.showerror("Error", "Passwords do not match")
            return
            
        hashed_password = self.hash_password(password)

        self.register_result_var.set("Creating account...")
        
        stub = self.get_lb_stub()
        if not stub:
            messagebox.showerror("Error", "No load balancer available")
            self.register_result_var.set("No load balancer available")
            return

        def on_success(response):
            if response.success:
                self.user_id = response.user_id
                self.current_username = username
                logger.info(f"Account created for {username} with ID {self.user_id}")
                self.register_result_var.set("Account created successfully")
                messagebox.showinfo("Success", "Your account has been created!")
                self.load_cart()
                self.switch_to_main()
            else:
                self.register_result_var.set("Username already exists")
                messagebox.showerror("Error", "Username already exists")

        def make_rpc():
            # Use the load balancer's imported CreateAccountRequest
            create_request = user_cart_pb2.CreateAccountRequest(username=username, password=hashed_password)
            return stub.CreateAccount(create_request)

        self.threaded_rpc("Create Account", make_rpc, on_success, self.create_account)
        

    def load_cart(self):
        """Load cart using background thread"""
        stub = self.get_lb_stub()
        if not stub:
            logger.warning("No load balancer available for cart loading")
            return

        def on_success(response):
            self.cart = {item.inventory_id: item.quantity for item in response.items}
            logger.info(f"Loaded cart for user {self.user_id}: {self.cart}")
            self.refresh_cart()

        def make_rpc():
            # Use the load balancer's UserRequest
            user_request = user_cart_pb2.UserRequest(user_id=self.user_id, username=self.current_username)
            return stub.GetCart(user_request)

        self.threaded_rpc("Load Cart", make_rpc, on_success, self.load_cart)
        

    def add_to_cart(self):
        """Add to cart using background thread"""
        idx = self.selected_inventory_index
        if idx is None:
            messagebox.showinfo("Selection Required", "Please select an inventory first")
            return
            
        item = self.inventory_items[idx]
        try:
            qty = int(self.quantity_entry.get())
            if qty <= 0:
                messagebox.showerror("Error", "Quantity must be positive")
                return
        except ValueError:
            messagebox.showerror("Error", "Invalid quantity")
            return
            
        logger.info(f"Adding {qty} of {item.name} to cart")
        
        stub = self.get_lb_stub()
        if not stub:
            messagebox.showerror("Error", "No load balancer available")
            return

        def on_success(response):
            self.cart[item.id] = self.cart.get(item.id, 0) + qty
            self.refresh_cart()
            messagebox.showinfo("Success", f"Added {qty} of {item.name} to your cart")
            
        def make_rpc():
            # Use the load balancer's Cart request format
            cart_request = load_balancer_pb2.LoadBalancerCartRequest(
                user_id=self.user_id, 
                inventory_id=item.id, 
                quantity=qty,
                username=self.current_username
            )
            return stub.AddToCart(cart_request)

        self.threaded_rpc("Add to Cart", make_rpc, on_success, self.add_to_cart, "Add to Cart")

        
    def remove_from_cart(self):
        """Remove from cart using background thread"""
        idx = self.selected_inventory_index
        if idx is None:
            messagebox.showinfo("Selection Required", "Please select an inventory to remove")
            return
            
        item = self.inventory_items[idx]
        
        if item.id not in self.cart:
            messagebox.showinfo("Not in Cart", "This item is not in your cart")
            return
            
        stub = self.get_lb_stub()
        if not stub:
            messagebox.showerror("Error", "No load balancer available")
            return

        def on_success(_):
            item_name = item.name
            quantity = self.cart.get(item.id, 0)
            self.cart.pop(item.id, None)
            self.refresh_cart()
            messagebox.showinfo("Success", f"Removed {item_name} from your cart")
            
        def make_rpc():
            # Use load balancer's cart request format with quantity=0 to indicate removal
            cart_request = load_balancer_pb2.LoadBalancerCartRequest(
                user_id=self.user_id, 
                inventory_id=item.id, 
                quantity=0,
                username=self.current_username
            )
            return stub.RemoveFromCart(cart_request)

        self.threaded_rpc("Remove from Cart", make_rpc, on_success, self.remove_from_cart, "Remove from Cart")

        
    def checkout(self):
        """Checkout using background thread"""
        if not self.cart:
            messagebox.showinfo("Info", "Your cart is empty")
            return
                
        stub = self.get_lb_stub()
        if not stub:
            messagebox.showerror("Error", "Load balancer unavailable")
            return

        # Show confirmation dialog
        items_text = "\n".join([f"- {next((i.name for i in self.inventory_items if i.id == id), f'Item {id}')}: {qty}" 
                            for id, qty in self.cart.items()])
        confirm = messagebox.askyesno("Confirm Checkout", 
                                    f"Are you sure you want to checkout with these items?\n\n{items_text}")
        
        if not confirm:
            return

        # Disable checkout button
        checkout_button = None
        for widget in self.main_frame.winfo_children():
            if isinstance(widget, tk.Button) and widget["text"] == "Checkout":
                widget.config(state=tk.DISABLED)
                checkout_button = widget

        # Now load balancer handles the entire checkout process atomically
        def process_checkout():
            try:
                self.status_var.set("Processing checkout...")
                
                # Single call to load balancer handles the entire checkout
                user_request = user_cart_pb2.UserRequest(user_id=self.user_id, username=self.current_username)
                stub.Checkout(user_request)
                
                # Get updated inventory after checkout
                response = stub.GetInventory(inventory_pb2.Empty())
                updated_items = list(response.items)
                
                # Update UI on success
                self.root.after(0, lambda: self._update_after_checkout(updated_items))
                
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                    logger.info("Checkout: Not leader error, refreshing leaders")
                    self.load_balancer_leader = None
                    self.root.after(500, self.checkout)
                else:
                    logger.error(f"Checkout error: {e.code()} - {e.details()}")
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Checkout failed: {e.details()}"))
                    self.root.after(0, lambda: self.status_var.set("Checkout failed"))
            finally:
                # Re-enable the checkout button
                if checkout_button:
                    self.root.after(0, lambda: checkout_button.config(state=tk.NORMAL))
                    
        # Run checkout process in background thread
        threading.Thread(target=process_checkout, daemon=True).start()

        
    def poll_inventory_loop(self):
        """Poll inventory service in background thread"""
        while True:
            try:
                if self.user_id is None:  # Stop polling if logged out
                    return
                    
                stub = self.get_lb_stub()
                if stub:
                    try:
                        # Use load balancer's Empty message for GetInventory
                        response = stub.GetInventory(inventory_pb2.Empty())
                        items = list(response.items)
                        
                        # Update UI on main thread
                        self.root.after(0, lambda i=items: self._update_inventory_items(i))
                        
                    except grpc.RpcError as e:
                        if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                            self.load_balancer_leader = None
                            logger.info("Inventory polling: Not leader error, refreshing leader")
                        else:
                            logger.debug(f"Error polling inventory: {e.code()}")
            except Exception as e:
                logger.error(f"Unexpected error in inventory polling: {str(e)}")
                
            time.sleep(POLL_INTERVAL)

            

    # Helper method for threading RPC calls
    def threaded_rpc(self, operation_name, rpc_function, on_success=None, on_error=None, button_text=None):
        """
        Execute an RPC call in a background thread to keep UI responsive
        
        Args:
            operation_name: Name of the operation (for logging)
            rpc_function: Function that performs the actual RPC call
            on_success: Function to call on successful RPC completion
            on_error: Function to call on RPC error
            button_text: Text of the button to disable during operation
        """
        # Disable button if specified
        disabled_button = None
        if button_text:
            for widget in self.main_frame.winfo_children():
                if isinstance(widget, tk.Button) and widget["text"] == button_text:
                    if widget.cget("state") == "disabled":  # Already in process
                        return  # Don't start another thread
                    widget.config(state=tk.DISABLED)
                    disabled_button = widget
        
        def run_in_thread():
            try:
                result = rpc_function()
                if on_success:
                    self.root.after(0, lambda: on_success(result))
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.FAILED_PRECONDITION and "Not leader" in e.details():
                    logger.info(f"{operation_name}: Not leader error, refreshing leaders")
                    # Extract leader info if available
                    leader_info = e.details().split("leader:")
                    if len(leader_info) > 1:
                        leader_addr = leader_info[1].strip()
                        logger.info(f"Error contains leader redirect: {leader_addr}")
                    
                    # Reset leader and retry
                    if on_error:
                        self.root.after(500, on_error)
                elif e.code() == grpc.StatusCode.ALREADY_EXISTS:
                    logger.error(f"Username already exists in threaded_rpc")
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Username already exists"))
                else:
                    logger.error(f"{operation_name} error: {e.code()} - {e.details()}")
                    # self.root.after(0, lambda: messagebox.showerror("Error", f"{operation_name} failed: {e.details()}"))
            except Exception as e2:
                logger.error(f"{operation_name} unexpected error: {str(e2)}")
                # self.root.after(0, lambda: messagebox.showerror("Error", f"Unexpected error: {str(e2)}"))
            finally:
                # Re-enable button if one was disabled
                if disabled_button:
                    self.root.after(0, lambda: disabled_button.config(state=tk.NORMAL))

        # Submit to thread pool instead of creating new thread
        self.thread_pool.submit(run_in_thread)
     
    def hash_password(self, password):
        """Hash a password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    def _update_after_checkout(self, updated_items):
        """Update UI after successful checkout"""
        self.inventory_items = updated_items
        self.refresh_inventory()
        self.cart.clear()
        self.refresh_cart()
        self.status_var.set("Checkout completed")
        messagebox.showinfo("Success", "Your order has been placed successfully!")

    def _update_inventory_items(self, items):
        """Update inventory items and refresh display"""
        self.inventory_items = items
        logger.info(f"Polled {len(items)} inventory items")
        self.refresh_inventory()

    def refresh_inventory(self):
        """Update the inventory listbox with current items"""
        if not hasattr(self, "inventory_listbox"):
            return

        # Save current selection
        try:
            current_selection = self.inventory_listbox.curselection()[0]
            current_id = self.inventory_items[current_selection].id
        except (IndexError, AttributeError):
            current_id = None

        # Refresh the list
        self.inventory_listbox.delete(0, tk.END)
        for item in self.inventory_items:
            self.inventory_listbox.insert(tk.END, f"{item.name}: {item.number} available")

        # Try to restore the same item if it's still there
        if current_id is not None:
            for i, item in enumerate(self.inventory_items):
                if item.id == current_id:
                    self.inventory_listbox.selection_set(i)
                    self.inventory_listbox.activate(i)
                    self.inventory_listbox.see(i)
                    break

        # Update timestamp
        now = time.strftime("%H:%M:%S")
        self.inventory_update_label.config(text=f"Last updated: {now}")

    def refresh_cart(self):
        """Update the cart display with current items"""
        if not self.cart:
            self.cart_display.config(text="Your cart is empty")
            return
            
        # Get names for items in cart
        cart_text = "Your Cart:\n"
        
        total_items = 0
        for item_id, qty in self.cart.items():
            item_name = "Unknown Item"
            # Find item name in inventory items
            for item in self.inventory_items:
                if item.id == item_id:
                    item_name = item.name
                    break
            
            cart_text += f"• {item_name}: {qty}\n"
            total_items += qty
            
        cart_text += f"\nTotal Items: {total_items}"
        self.cart_display.config(text=cart_text)


    # GUI methods
    def create_login_frame(self):
        """Create the login view with improved styling"""
        frame = ttk.Frame(self.main_container, style='TFrame')
        
        # Create notebook for tabs
        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Login tab
        login_tab = ttk.Frame(notebook, padding=20)
        notebook.add(login_tab, text="Login")
        
        # Create account tab
        register_tab = ttk.Frame(notebook, padding=20)
        notebook.add(register_tab, text="Create Account")
        
        # Login tab contents
        ttk.Label(login_tab, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.username_entry = ttk.Entry(login_tab, width=30)
        self.username_entry.grid(row=0, column=1, sticky=tk.W, pady=10)
        
        # Add password field
        ttk.Label(login_tab, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=10)
        self.password_entry = ttk.Entry(login_tab, width=30, show="•")
        self.password_entry.grid(row=1, column=1, sticky=tk.W, pady=10)
        
        # Login buttons
        login_button = ttk.Button(login_tab, text="Login", 
                                 command=self.login, 
                                 style='Action.TButton')
        login_button.grid(row=2, column=1, sticky=tk.E, pady=20)
        
        # Login result message
        self.login_result_var = tk.StringVar()
        self.login_result = ttk.Label(login_tab, textvariable=self.login_result_var)
        self.login_result.grid(row=3, column=0, columnspan=2, pady=10)

        # Create account tab contents
        ttk.Label(register_tab, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.register_username = ttk.Entry(register_tab, width=30)
        self.register_username.grid(row=0, column=1, sticky=tk.W, pady=10)
        
        # Add password field
        ttk.Label(register_tab, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=10)
        self.register_password = ttk.Entry(register_tab, width=30, show="•")
        self.register_password.grid(row=1, column=1, sticky=tk.W, pady=10)
        
        # Add confirm password field
        ttk.Label(register_tab, text="Confirm Password:").grid(row=2, column=0, sticky=tk.W, pady=10)
        self.register_confirm_password = ttk.Entry(register_tab, width=30, show="•")
        self.register_confirm_password.grid(row=2, column=1, sticky=tk.W, pady=10)
        
        # Register button
        register_button = ttk.Button(register_tab, text="Create Account", 
                                   command=self.create_account, 
                                   style='Action.TButton')
        register_button.grid(row=3, column=1, sticky=tk.E, pady=20)
        
        # Register result message
        self.register_result_var = tk.StringVar()
        self.register_result = ttk.Label(register_tab, textvariable=self.register_result_var)
        self.register_result.grid(row=4, column=0, columnspan=2, pady=10)
        return frame
        
    def create_main_frame(self):
        """Create the main application view with improved styling"""
        frame = ttk.Frame(self.main_container, style='TFrame')
        
        # Welcome message
        self.welcome_label = ttk.Label(frame, text="", style='Header.TLabel')
        self.welcome_label.pack(pady=(0, 20))
        
        # Left panel - inventory
        left_panel = ttk.Frame(frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        ttk.Label(left_panel, text="Available Inventory", font=('Arial', 14, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        # Inventory list with scrollbar
        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.inventory_listbox = tk.Listbox(list_frame, font=('Arial', 12), 
                                          yscrollcommand=scrollbar.set,
                                          selectbackground='#a6d4fa',
                                          height=10)
        self.inventory_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.inventory_listbox.yview)
        
        # Bind selection event
        self.inventory_listbox.bind("<<ListboxSelect>>", self.on_item_select)
        
        # Last updated label
        self.inventory_update_label = ttk.Label(left_panel, text="", style='Status.TLabel')
        self.inventory_update_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Right panel - Cart
        right_panel = ttk.Frame(frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)
        
        ttk.Label(right_panel, text="Your Cart", font=('Arial', 14, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        # Cart display
        cart_frame = ttk.Frame(right_panel, relief=tk.GROOVE, borderwidth=1)
        cart_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.cart_display = ttk.Label(cart_frame, text="Your cart is empty", 
                                    wraplength=200, justify=tk.LEFT)
        self.cart_display.pack(padx=10, pady=10, fill=tk.BOTH)
        
        # Quantity selector
        qty_frame = ttk.Frame(right_panel)
        qty_frame.pack(fill=tk.X, pady=(20, 10))
        
        ttk.Label(qty_frame, text="Quantity:").pack(side=tk.LEFT)
        
        self.quantity_entry = ttk.Spinbox(qty_frame, from_=1, to=100, width=5)
        self.quantity_entry.pack(side=tk.LEFT, padx=10)
        self.quantity_entry.delete(0, tk.END)
        self.quantity_entry.insert(0, "1")
        
        # Action buttons
        button_frame = ttk.Frame(right_panel)
        button_frame.pack(fill=tk.X, pady=10)

        # Define button styles with proper colors
        self.style.configure("Green.TButton", background="#4CAF50", foreground="black", font=('Arial', 12))
        self.style.map("Green.TButton",
            background=[('active', '#45a049'), ('pressed', '#3d8b40')],
            relief=[('pressed', 'sunken'), ('!pressed', 'raised')])

        self.style.configure("Red.TButton", background="#f44336", foreground="black", font=('Arial', 12))
        self.style.map("Red.TButton",
            background=[('active', '#e53935'), ('pressed', '#d32f2f')],
            relief=[('pressed', 'sunken'), ('!pressed', 'raised')])

        self.style.configure("Blue.TButton", background="#2196F3", foreground="black", font=('Arial', 12))
        self.style.map("Blue.TButton",
            background=[('active', '#1e88e5'), ('pressed', '#1976d2')],
            relief=[('pressed', 'sunken'), ('!pressed', 'raised')])

        self.style.configure("Gray.TButton", background="#9e9e9e", foreground="black", font=('Arial', 12))
        self.style.map("Gray.TButton",
            background=[('active', '#8f8f8f'), ('pressed', '#7e7e7e')],
            relief=[('pressed', 'sunken'), ('!pressed', 'raised')])

        # Create styled buttons
        add_btn = ttk.Button(button_frame, text="Add to Cart", style="Green.TButton",
                            command=self.add_to_cart)
        add_btn.pack(fill=tk.X, pady=5)

        remove_btn = ttk.Button(button_frame, text="Remove from Cart", style="Red.TButton", 
                                command=self.remove_from_cart)
        remove_btn.pack(fill=tk.X, pady=5)

        checkout_btn = ttk.Button(button_frame, text="Checkout", style="Blue.TButton",
                                command=self.checkout)
        checkout_btn.pack(fill=tk.X, pady=5)

        # Logout button
        logout_btn = ttk.Button(button_frame, text="Logout", style="Gray.TButton",
                            command=self.logout)
        logout_btn.pack(fill=tk.X, pady=(20, 5))
        
        return frame

    def on_item_select(self, event):
        if not self.inventory_listbox.curselection():
            self.selected_inventory_index = None
        else:
            self.selected_inventory_index = self.inventory_listbox.curselection()[0]
            logger.info(f"Selected inventory index: {self.selected_inventory_index}")

    def switch_to_main(self):
        """Switch to main view and update welcome message"""
        self.login_frame.pack_forget()
        
        # Update welcome message
        self.welcome_label.config(text=f"Welcome, {self.current_username}!")
        
        # Show main frame
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Start polling for inventory updates
        threading.Thread(target=self.poll_inventory_loop, daemon=True).start()
    
    def logout(self):
        """Logout and return to login screen"""
        self.main_frame.pack_forget()
        self.user_id = None
        self.current_username = ""
        self.current_shard = None
        self.cart = {}
        
        # Reset login fields
        self.username_entry.delete(0, tk.END)
        self.login_result_var.set("")
        self.password_entry.delete(0, tk.END)
        self.register_result_var.set("")
        self.register_username.delete(0, tk.END)
        self.register_password.delete(0, tk.END)
        self.register_confirm_password.delete(0, tk.END)
        
        # Show login frame
        self.login_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)


if __name__ == "__main__":
    root = tk.Tk()
    app = ClientApp(root)
    root.mainloop()