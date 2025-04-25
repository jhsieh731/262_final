import subprocess
import time
from run_all_replicas import run_replicas

def test_run_replicas(monkeypatch, tmp_path):
    # Prepare dummy replicas list
    replicas = [
        {"host": "127.0.0.1", "port": 8000, "db": "db0.db"},
        {"host": "127.0.0.1", "port": 8001, "db": "db1.db"}
    ]
    # Capture popen calls
    calls = []
    class DummyProc:
        def __init__(self): pass
        def poll(self): return None
        def terminate(self): pass
    def fake_popen(cmd, stdout, stderr):
        calls.append(cmd)
        return DummyProc()
    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    # Run replicas
    procs = run_replicas('kind', replicas, 'script.py')
    # Should launch two processes
    assert set(procs.keys()) == {'kind0', 'kind1'}
    assert len(calls) == 2
    # Check command format
    for cmd, rep in zip(calls, replicas):
        assert 'script.py' in cmd[1] or cmd[0] == 'python'
        assert '--host' in cmd and '--port' in cmd and '--db' in cmd
