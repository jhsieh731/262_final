import json
import io
import builtins
import pytest
import run_all_replicas

class DummyProc:
    def __init__(self, name):
        self.name = name
        self.terminated = False
    def poll(self):
        return None
    def terminate(self):
        self.terminated = True


def test_load_config(tmp_path, monkeypatch):
    # Write a temporary config.json and ensure load_config reads it
    config = {"foo": "bar"}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    loaded = run_all_replicas.load_config()
    assert loaded == config


def test_main_list_and_exit(monkeypatch, capsys):
    # Stub load_config and run_replicas to avoid real subprocesses
    config = {"shard1": [{}], "shard2": [{}], "inventory": [{}]}
    monkeypatch.setattr(run_all_replicas, 'load_config', lambda: config)
    procs = []
    def fake_run(kind, replicas, script):
        name = f"{kind}0"
        proc = DummyProc(name)
        procs.append(proc)
        return {name: (proc, io.StringIO())}
    monkeypatch.setattr(run_all_replicas, 'run_replicas', fake_run)
    monkeypatch.setattr(run_all_replicas.time, 'sleep', lambda s: None)
    # Simulate user typing 'list' then 'exit'
    inputs = iter(['list', 'exit'])
    monkeypatch.setattr(builtins, 'input', lambda prompt=None: next(inputs))

    run_all_replicas.main()
    out = capsys.readouterr().out
    assert "Spawning all replicas" in out
    for kind in ['s1r', 's2r', 'it']:
        assert f"{kind}0: alive" in out
    assert "[shutdown] Killing all remaining processes..." in out
    assert "[done]" in out
    assert all(p.terminated for p in procs)


def test_main_kill_and_exit(monkeypatch, capsys):
    # Stub services again
    config = {"shard1": [{}], "shard2": [{}], "inventory": [{}]}
    monkeypatch.setattr(run_all_replicas, 'load_config', lambda: config)
    procs = []
    def fake_run(kind, replicas, script):
        name = f"{kind}0"
        proc = DummyProc(name)
        procs.append(proc)
        return {name: (proc, io.StringIO())}
    monkeypatch.setattr(run_all_replicas, 'run_replicas', fake_run)
    monkeypatch.setattr(run_all_replicas.time, 'sleep', lambda s: None)
    # Simulate killing one replica then exit
    inputs = iter(['kill s1r0', 'exit'])
    monkeypatch.setattr(builtins, 'input', lambda prompt=None: next(inputs))

    run_all_replicas.main()
    out = capsys.readouterr().out
    assert "[kill] s1r0 terminated" in out
    assert "[shutdown] Killing all remaining processes..." in out
    assert all(p.terminated for p in procs)
