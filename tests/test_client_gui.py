import pytest
import json
import os
import sys
import importlib

# Ensure tests can reload module
MODULE_NAME = 'client_gui'


def test_load_config(tmp_path, monkeypatch):
    # Create temporary config.json and ensure load_config reads it via env var
    config_data = {"shard1": [{"host": "h1", "port": 111}], "shard2": [], "inventory": []}
    cfg_file = tmp_path / "client_config.json"
    cfg_file.write_text(json.dumps(config_data))
    # Point load_config to our file
    monkeypatch.setenv("CLIENT_GUI_CONFIG_PATH", str(cfg_file))
    # Reload module to pick up new config
    if MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    client_gui = importlib.import_module(MODULE_NAME)
    assert hasattr(client_gui, 'config')
    assert client_gui.config == config_data


def test_create_stub_list(monkeypatch):
    import client_gui
    # Stub insecure_channel
    monkeypatch.setattr(client_gui.grpc, 'insecure_channel', lambda url: f"chan_{url}")
    class Stub:
        def __init__(self, channel):
            self.channel = channel
    replicas = [("host1", 8000), ("host2", 9000)]
    stubs = client_gui.create_stub_list(replicas, Stub)
    # Verify stub list format and channel URLs
    expected = [(("host1", 8000), f"chan_host1:8000"), (("host2", 9000), f"chan_host2:9000")]
    result = [(addr, stub.channel) for addr, stub in stubs]
    assert result == expected


def test_set_leader_tracking():
    # Test that leader setter methods update attributes correctly
    import importlib
    client_gui = importlib.import_module(MODULE_NAME)
    # Instantiate ClientApp without calling __init__
    app = client_gui.ClientApp.__new__(client_gui.ClientApp)
    # Initialize leader attributes
    app.shard1_leader = None
    app.shard2_leader = None
    app.inventory_leader = None
    # Test set_shard1_leader
    app.set_shard1_leader(("h1", 1))
    assert app.shard1_leader == ("h1", 1)
    # No change on same leader
    app.set_shard1_leader(("h1", 1))
    # Test set_shard2_leader
    app.set_shard2_leader(("h2", 2))
    assert app.shard2_leader == ("h2", 2)
    # Test set_inventory_leader
    app.set_inventory_leader(("h3", 3))
    assert app.inventory_leader == ("h3", 3)
