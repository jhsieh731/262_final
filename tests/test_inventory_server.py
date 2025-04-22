import json
import sqlite3
import logging
import pytest
from inventory_server import InventoryServer

@pytest.fixture
def server(tmp_path):
    db_path = str(tmp_path / "inv.db")
    srv = InventoryServer("localhost", 7000, [], db_path)
    return srv


def test_init_db_and_seed(server):
    conn = sqlite3.connect(server.db_path)
    cur = conn.cursor()
    cur.execute("SELECT name, number FROM inventory ORDER BY id")
    rows = cur.fetchall()
    assert rows == [
        ("Flight to Paris", 10),
        ("Hotel in Rome", 20),
        ("Car Rental in London", 15),
        ("Beach Resort in Bali", 5),
        ("Mountain Retreat in Switzerland", 8),
    ]

def test_apply_command_update(server):
    # decrease
    cmd = json.dumps({"action": "update_inventory", "inventory_id": 1, "quantity_change": -5})
    assert server.apply_command(cmd) is True
    conn = sqlite3.connect(server.db_path)
    cur = conn.cursor()
    cur.execute("SELECT number FROM inventory WHERE id=1")
    assert cur.fetchone()[0] == 5
    # increase
    cmd2 = json.dumps({"action": "update_inventory", "inventory_id": 1, "quantity_change": 3})
    assert server.apply_command(cmd2) is True
    cur.execute("SELECT number FROM inventory WHERE id=1")
    assert cur.fetchone()[0] == 8


def test_apply_command_insufficient(server, caplog):
    caplog.set_level(logging.WARNING)
    cmd = json.dumps({"action": "update_inventory", "inventory_id": 1, "quantity_change": -100})
    assert server.apply_command(cmd) is False
    assert "Not enough inventory" in caplog.text


def test_unknown_action(server, caplog):
    caplog.set_level(logging.WARNING)
    cmd = json.dumps({"action": "foo"})
    assert server.apply_command(cmd) is False
    assert "Unknown command action" in caplog.text


def test_heartbeat_no_raft(server):
    import grpc
    class DummyContext:
        def __init__(self):
            self.code = None
            self.details = None
        def set_code(self, code): self.code = code
        def set_details(self, details): self.details = details
    ctx = DummyContext()
    resp = server.Heartbeat(None, ctx)
    assert resp.is_leader is False
    assert ctx.code == grpc.StatusCode.FAILED_PRECONDITION
    assert 'Current leader:' in ctx.details


def test_apply_command_invalid_json(server):
    assert server.apply_command("not a valid json") is False
