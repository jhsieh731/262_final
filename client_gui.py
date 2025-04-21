import tkinter as tk
from tkinter import messagebox
import grpc
import threading
import time
import random
import logging 

from proto import user_cart_pb2, user_cart_pb2_grpc
from proto import itinerary_pb2, itinerary_pb2_grpc

SHARD_1_REPLICAS = [("localhost", 5000), ("localhost", 5001), ("localhost", 5002)]
SHARD_2_REPLICAS = [("localhost", 6000), ("localhost", 6001), ("localhost", 6002)]
ITINERARY_REPLICAS = [("localhost", 7100), ("localhost", 7101), ("localhost", 7102)]

POLL_INTERVAL = 5  # seconds

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
file_handler = logging.FileHandler('client_app.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def create_stub_list(replicas, stub_class):
    return [(addr, stub_class(grpc.insecure_channel(f"{addr[0]}:{addr[1]}"))) for addr in replicas]

class ClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Shopping Cart")

        self.user_id = None
        self.current_username = ""
        self.current_shard = None
        self.cart = {}
        self.itinerary_items = []
        self.selected_itinerary_index = None


        self.shard1_leader = None
        self.shard2_leader = None
        self.itinerary_leader = None

        self.shard1_stubs = create_stub_list(SHARD_1_REPLICAS, user_cart_pb2_grpc.UserCartServiceStub)
        self.shard2_stubs = create_stub_list(SHARD_2_REPLICAS, user_cart_pb2_grpc.UserCartServiceStub)
        self.itinerary_stubs = create_stub_list(ITINERARY_REPLICAS, itinerary_pb2_grpc.ItineraryServiceStub)

        self._start_heartbeat_threads()

        self.login_frame = self.build_login_frame()
        self.main_frame = self.build_main_frame()

        self.login_frame.pack()

    def _start_heartbeat_threads(self):
        def monitor(stubs, update_leader_fn):
            while True:
                leaders = []
                for (host, port), stub in stubs:
                    try:
                        response = stub.Heartbeat(user_cart_pb2.HeartbeatRequest(host=host, port=port), timeout=0.5)
                        if response.is_leader:
                            leaders.append((host, port))
                    except grpc.RpcError:
                        pass
                if leaders:
                    update_leader_fn(min(leaders))
                time.sleep(2)

        threading.Thread(target=lambda: monitor(self.shard1_stubs, self.set_shard1_leader), daemon=True).start()
        threading.Thread(target=lambda: monitor(self.shard2_stubs, self.set_shard2_leader), daemon=True).start()
        threading.Thread(target=self.monitor_itinerary_leader, daemon=True).start()

    def set_shard1_leader(self, leader):
        prev = self.shard1_leader
        if prev != leader:
            logger.info(f"Shard 1 leader changed from {prev} to {leader}")
        self.shard1_leader = leader

    def set_shard2_leader(self, leader):
        prev = self.shard2_leader
        if prev != leader:
            logger.info(f"Shard 2 leader changed from {prev} to {leader}")
        self.shard2_leader = leader

    def set_itinerary_leader(self, leader):
        prev = self.itinerary_leader
        if prev != leader:
            logger.info(f"Itinerary leader changed from {prev} to {leader}")
        self.itinerary_leader = leader

    def monitor_itinerary_leader(self):
        while True:
            leaders = []
            for (host, port), stub in self.itinerary_stubs:
                try:
                    response = stub.Heartbeat(itinerary_pb2.HeartbeatRequest(host=host, port=port), timeout=0.5)
                    if response.is_leader:
                        leaders.append((host, port))
                except grpc.RpcError:
                    pass
            if leaders:
                new_leader = min(leaders)
                if new_leader != self.itinerary_leader:
                    self.set_itinerary_leader(new_leader)
            time.sleep(2)

    def on_item_select(self, event):
        if not self.itinerary_listbox.curselection():
            self.selected_itinerary_index = None
        else:
            self.selected_itinerary_index = self.itinerary_listbox.curselection()[0]
        logger.info(f"Selected itinerary index: {self.selected_itinerary_index}")


    def build_login_frame(self):
        frame = tk.Frame(self.root)
        tk.Label(frame, text="Username:").pack()
        self.username_entry = tk.Entry(frame)
        self.username_entry.pack()
        tk.Button(frame, text="Login", command=self.login).pack()
        tk.Button(frame, text="Create Account", command=self.create_account).pack()
        return frame

    def build_main_frame(self):
        frame = tk.Frame(self.root)

        self.cart_label = tk.Label(frame, text="Cart:")
        self.cart_label.pack()

        self.itinerary_listbox = tk.Listbox(frame)
        self.itinerary_listbox.pack()
        self.itinerary_listbox.bind("<<ListboxSelect>>", self.on_item_select)


        self.itinerary_update_label = tk.Label(frame, text="")
        self.itinerary_update_label.pack()

        self.quantity_entry = tk.Entry(frame)
        self.quantity_entry.pack()
        self.quantity_entry.insert(0, "1")

        tk.Button(frame, text="Add to Cart", command=self.add_to_cart).pack()
        tk.Button(frame, text="Remove from Cart", command=self.remove_from_cart).pack()
        tk.Button(frame, text="Checkout", command=self.checkout).pack()

        return frame

    def login(self):
        username = self.username_entry.get().strip()
        for leader, stub in [(self.shard1_leader, self.get_shard1_stub()),
                             (self.shard2_leader, self.get_shard2_stub())]:
            if leader is None:
                continue
            try:
                response = stub.Login(user_cart_pb2.LoginRequest(username=username))
                if response.success:
                    self.user_id = response.user_id
                    self.current_username = username
                    self.current_shard = 1 if stub == self.get_shard1_stub() else 2
                    logger.info(f"User {username} logged in with ID {self.user_id} on shard {self.current_shard}")
                    self.load_cart()
                    self.switch_to_main()
                    return
            except grpc.RpcError:
                continue
        messagebox.showerror("Error", "User not found")

    def create_account(self):
        username = self.username_entry.get().strip()
        target_shard = 1 if random.choice([True, False]) else 2
        stub = self.get_shard1_stub() if target_shard == 1 else self.get_shard2_stub()
        if stub is None:
            messagebox.showerror("Error", "No leader available")
            return
        try:
            response = stub.CreateAccount(user_cart_pb2.CreateAccountRequest(username=username))
            if response.success:
                self.user_id = response.user_id
                self.current_username = username
                self.current_shard = target_shard
                self.load_cart()
                self.switch_to_main()
            else:
                messagebox.showerror("Error", "Username already exists")
        except grpc.RpcError:
            messagebox.showerror("Error", "Server unavailable")

    def switch_to_main(self):
        self.login_frame.pack_forget()
        self.main_frame.pack()
        threading.Thread(target=self.poll_itinerary_loop, daemon=True).start()

    def poll_itinerary_loop(self):
        while True:
            try:
                stub = self.get_itinerary_stub()
                if stub:
                    response = stub.GetItinerary(itinerary_pb2.Empty())
                    self.itinerary_items = list(response.items)
                    logger.info(f"Polled itinerary items: {self.itinerary_items}")
                    self.refresh_itinerary()
            except grpc.RpcError:
                pass
            time.sleep(POLL_INTERVAL)


    def refresh_itinerary(self):
        if not hasattr(self, "itinerary_listbox"):
            return

        # 🔒 Save current selection
        try:
            current_selection = self.itinerary_listbox.curselection()[0]
            current_id = self.itinerary_items[current_selection].id
        except IndexError:
            current_id = None

        # 🧹 Refresh the list
        self.itinerary_listbox.delete(0, tk.END)
        for item in self.itinerary_items:
            self.itinerary_listbox.insert(tk.END, f"{item.name}: {item.number}")

        # 🔁 Try to restore the same item if it's still there
        if current_id is not None:
            for i, item in enumerate(self.itinerary_items):
                if item.id == current_id:
                    self.itinerary_listbox.selection_set(i)
                    self.itinerary_listbox.activate(i)
                    break

        now = time.strftime("%H:%M:%S")
        self.itinerary_update_label.config(text=f"Last updated: {now}")

    def load_cart(self):
        stub = self.get_user_cart_stub()
        if not stub:
            return
        try:
            response = stub.GetCart(user_cart_pb2.UserRequest(user_id=self.user_id))
            self.cart = {item.itinerary_id: item.quantity for item in response.items}
            logger.info(f"Loaded cart for user {self.user_id}: {self.cart}")
            self.refresh_cart()
        except grpc.RpcError:
            pass

    def refresh_cart(self):
        self.cart_label.config(text=f"Cart: {self.cart}")

    def add_to_cart(self):
        idx = self.selected_itinerary_index
        if idx is None:
            return
        item = self.itinerary_items[idx]
        qty = int(self.quantity_entry.get())
        logger.info(f"Adding {qty} of {item.name} to cart")
        stub = self.get_user_cart_stub()
        if not stub:
            return
        try:
            stub.AddToCart(user_cart_pb2.UpdateCartRequest(
                user_id=self.user_id, itinerary_id=item.id, quantity=qty))
            self.cart[item.id] = self.cart.get(item.id, 0) + qty
            self.refresh_cart()
        except grpc.RpcError as e:
            logger.error(f"Failed to add to cart: {e.code()} - {e.details()}")


    def remove_from_cart(self):
        # idx = self.itinerary_listbox.curselection()
        # if not idx:
        #     return
        # item = self.itinerary_items[idx[0]]
        idx = self.selected_itinerary_index
        if idx is None:
            return
        item = self.itinerary_items[idx]

        stub = self.get_user_cart_stub()
        if not stub:
            return
        try:
            stub.RemoveFromCart(user_cart_pb2.UpdateCartRequest(
                user_id=self.user_id, itinerary_id=item.id, quantity=0))
            self.cart.pop(item.id, None)
            self.refresh_cart()
        except grpc.RpcError:
            pass

    def checkout(self):
        cart_stub = self.get_user_cart_stub()
        itin_stub = self.get_itinerary_stub()
        if not cart_stub or not itin_stub:
            messagebox.showerror("Error", "Leader unavailable")
            return
        try:
            for itinerary_id, qty in self.cart.items():
                itin_stub.UpdateItinerary(itinerary_pb2.UpdateRequest(
                    itinerary_id=itinerary_id, quantity_change=qty))

            response = itin_stub.GetItinerary(itinerary_pb2.Empty())
            self.itinerary_items = list(response.items)
            self.refresh_itinerary()

            cart_stub.Checkout(user_cart_pb2.UserRequest(user_id=self.user_id))
            self.cart.clear()
            self.refresh_cart()
        except grpc.RpcError:
            messagebox.showerror("Error", "Checkout failed")

    def get_user_cart_stub(self):
        if self.current_shard == 1:
            return self.get_shard1_stub()
        else:
            return self.get_shard2_stub()

    def get_shard1_stub(self):
        if self.shard1_leader:
            return next((stub for (h, p), stub in self.shard1_stubs if (h, p) == self.shard1_leader), None)

    def get_shard2_stub(self):
        if self.shard2_leader:
            return next((stub for (h, p), stub in self.shard2_stubs if (h, p) == self.shard2_leader), None)

    def get_itinerary_stub(self):
        if self.itinerary_leader:
            return next((stub for (h, p), stub in self.itinerary_stubs if (h, p) == self.itinerary_leader), None)

if __name__ == "__main__":
    root = tk.Tk()
    app = ClientApp(root)
    root.mainloop()
