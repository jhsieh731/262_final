import json
import sqlite3
import pytest
import grpc
from shard_server import ShardServer
from proto import user_cart_pb2

class DummyContext:
    def __init__(self):
        self.code = None
        self.details = None
    def set_code(self, code):
        self.code = code
    def set_details(self, details):
        self.details = details

@pytest.fixture
def server(tmp_path):
    db_path = str(tmp_path / "test.db")
    srv = ShardServer("localhost", 5000, [], db_path)
    return srv

def test_heartbeat(server):
    # Without raft_node
    ctx = DummyContext()
    resp = server.Heartbeat(None, ctx)
    assert resp.is_leader is False
    # With leader
    class LeaderStub: state = "Leader"
    server.raft_node = LeaderStub()
    resp2 = server.Heartbeat(None, None)
    assert resp2.is_leader is True

def test_login_rpc(server):
    # Seed a user
    server.apply_command(json.dumps({"action":"create_account","username":"u","password":"p"}))
    req_ok = user_cart_pb2.LoginRequest(username="u", password="p")
    resp_ok = server.Login(req_ok, None)
    assert resp_ok.success and resp_ok.user_id == 1
    # Wrong creds
    req_bad = user_cart_pb2.LoginRequest(username="x", password="y")
    resp_bad = server.Login(req_bad, None)
    assert not resp_bad.success

def test_create_account_rpc(server):
    req = user_cart_pb2.CreateAccountRequest(username="a", password="pw")
    # No raft_node
    ctx1 = DummyContext()
    resp1 = server.CreateAccount(req, ctx1)
    assert not resp1.success
    assert ctx1.code == grpc.StatusCode.UNAVAILABLE
    # Not leader
    class FollowerStub: state = "Follower"
    server.raft_node = FollowerStub()
    ctx2 = DummyContext()
    resp2 = server.CreateAccount(req, ctx2)
    assert not resp2.success
    assert ctx2.code == grpc.StatusCode.FAILED_PRECONDITION
    # Leader: stub submit_command applies and returns True
    class LeaderStub:
        state = "Leader"
        def submit_command(self, cmd):
            server.apply_command(cmd)
            return True
    server.raft_node = LeaderStub()
    resp3 = server.CreateAccount(req, None)
    assert resp3.success and resp3.user_id == 1

def test_cart_rpc_and_get_checkout(server):
    # Prepare leader stub
    commands = []
    class LeaderStub:
        state = "Leader"
        def submit_command(self, cmd):
            commands.append(cmd)
            # Apply command locally for GET/Remove tests
            try:
                server.apply_command(cmd)
            except Exception:
                pass
            return True
    # Test AddToCart errors
    req = user_cart_pb2.UpdateCartRequest(user_id=1, inventory_id=5, quantity=2)
    ctx1 = DummyContext()
    resp1 = server.AddToCart(req, ctx1)
    # No raft_node => UNAVAILABLE
    assert ctx1.code == grpc.StatusCode.UNAVAILABLE
    # Not leader
    class FStub: state = "Follower"
    server.raft_node = FStub()
    ctx2 = DummyContext()
    resp2 = server.AddToCart(req, ctx2)
    assert resp2.items == []
    assert ctx2.code == grpc.StatusCode.FAILED_PRECONDITION
    # Leader success
    server.raft_node = LeaderStub()
    resp3 = server.AddToCart(req, None)
    assert any("add_to_cart" in c for c in commands)
    # Now GET should return item
    get_resp = server.GetCart(user_cart_pb2.UserRequest(user_id=1), None)
    assert len(get_resp.items) == 1 and get_resp.items[0].inventory_id == 5
    # RemoveFromCart RPC
    commands.clear()
    server.raft_node = LeaderStub()
    rem_req = user_cart_pb2.UpdateCartRequest(user_id=1, inventory_id=5, quantity=0)
    rem_resp = server.RemoveFromCart(rem_req, None)
    assert any("remove_from_cart" in c for c in commands)
    # After removal, GetCart yields no items
    empty = server.GetCart(user_cart_pb2.UserRequest(user_id=1), None)
    assert empty.items == []
    # Checkout RPC errors and success
    # Remove raft_node attribute to simulate uninitialized state
    if hasattr(server, 'raft_node'):
        delattr(server, 'raft_node')
    ctx3 = DummyContext()
    chk1 = server.Checkout(user_cart_pb2.UserRequest(user_id=1), ctx3)
    assert not chk1.success and ctx3.code == grpc.StatusCode.UNAVAILABLE
    server.raft_node = FStub()
    ctx4 = DummyContext()
    chk2 = server.Checkout(user_cart_pb2.UserRequest(user_id=1), ctx4)
    assert not chk2.success and ctx4.code == grpc.StatusCode.FAILED_PRECONDITION
    # Leader checkout (no items left)
    commands.clear()
    server.raft_node = LeaderStub()
    chk3 = server.Checkout(user_cart_pb2.UserRequest(user_id=1), None)
    assert any("checkout" in c for c in commands)
    assert chk3.success
