import json
import sqlite3
import os
import pytest
from shard_server import ShardServer

@pytest.fixture
def server(tmp_path):
    db_path = str(tmp_path / "test.db")
    return ShardServer("localhost", 5000, [], db_path)

def test_create_account(server):
    cmd = json.dumps({"action": "create_account", "username": "alice", "password": "pw"})
    server.apply_command(cmd)
    conn = sqlite3.connect(server.db_path)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users")
    assert cur.fetchall() == [("alice",)]
    # Duplicate is ignored
    server.apply_command(cmd)
    cur.execute("SELECT COUNT(*) FROM users")
    assert cur.fetchone()[0] == 1

def test_cart_operations(server):
    # create user
    server.apply_command(json.dumps({"action": "create_account", "username": "bob", "password": "pw"}))
    user_id = 1
    # add to cart
    add_cmd = json.dumps({"action": "add_to_cart", "user_id": user_id, "inventory_id": 42, "quantity": 3})
    server.apply_command(add_cmd)
    conn = sqlite3.connect(server.db_path)
    cur = conn.cursor()
    cur.execute("SELECT quantity, is_deleted FROM cart WHERE user_id=? AND inventory_id=?", (user_id,42))
    qty, deleted = cur.fetchone()
    assert qty == 3 and deleted == 0
    # remove item
    server.apply_command(json.dumps({"action": "remove_from_cart", "user_id": user_id, "inventory_id": 42}))
    cur.execute("SELECT is_deleted FROM cart WHERE user_id=? AND inventory_id=?", (user_id,42))
    assert cur.fetchone()[0] == 1
    # checkout resets all
    server.apply_command(json.dumps({"action": "add_to_cart", "user_id": user_id, "inventory_id": 43, "quantity": 2}))
    server.apply_command(json.dumps({"action": "checkout", "user_id": user_id}))
    cur.execute("SELECT COUNT(*) FROM cart WHERE user_id=? AND is_deleted=0", (user_id,))
    assert cur.fetchone()[0] == 0

def test_add_to_cart_accumulate(server):
    import json, sqlite3
    # create account and add twice to same item
    server.apply_command(json.dumps({"action":"create_account","username":"c","password":"pw"}))
    uid = 1
    server.apply_command(json.dumps({"action":"add_to_cart","user_id":uid,"inventory_id":100,"quantity":2}))
    server.apply_command(json.dumps({"action":"add_to_cart","user_id":uid,"inventory_id":100,"quantity":3}))
    conn = sqlite3.connect(server.db_path)
    cur = conn.cursor()
    cur.execute("SELECT quantity FROM cart WHERE user_id=? AND inventory_id=?", (uid,100))
    assert cur.fetchone()[0] == 5

def test_apply_command_invalid_json_shard(server):
    # should not raise on invalid JSON
    server.apply_command("not a json")
