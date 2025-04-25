import pytest
import time
import raft_node
from raft_node import RaftNode, set_raft_logger
from proto import raft_pb2

@ pytest.fixture(autouse=True)
def disable_threads(monkeypatch):
    # Prevent background election timer and heartbeat threads
    class DummyThread:
        def __init__(self, target=None, daemon=False):
            self.target = target
        def start(self):
            pass
    monkeypatch.setattr(raft_node.threading, 'Thread', DummyThread)

@ pytest.fixture
def dummy_callback():
    calls = []
    return calls, lambda cmd: calls.append(cmd)

@ pytest.fixture
def node(dummy_callback):
    calls, callback = dummy_callback
    node = RaftNode('node1', [], callback)
    # Stop in leader state not needed
    return node


def test_random_election_timeout(monkeypatch):
    # Force random.uniform to known value
    monkeypatch.setattr(raft_node.random, 'uniform', lambda a, b: 3.14)
    timeout = RaftNode('id', [], lambda x: None)._random_election_timeout()
    assert timeout == 3.14


def test_reset_election_timer(monkeypatch):
    # Control time and random
    times = [100.0]
    monkeypatch.setattr(raft_node.time, 'time', lambda: times[0])
    monkeypatch.setattr(raft_node.random, 'uniform', lambda a, b: 2.5)
    node = RaftNode('id', [], lambda x: None)
    # Advance time before reset
    times[0] = 200.0
    node._reset_election_timer()
    assert node.election_timeout == 2.5
    assert node.last_heartbeat == 200.0


def test_log_levels(monkeypatch):
    # Dummy logger to capture messages
    class DummyLogger:
        def __init__(self): self.msgs = []
        def debug(self, m): self.msgs.append(('DEBUG', m))
        def info(self, m): self.msgs.append(('INFO', m))
        def warning(self, m): self.msgs.append(('WARNING', m))
        def error(self, m): self.msgs.append(('ERROR', m))
    dummy = DummyLogger()
    set_raft_logger(dummy)
    node = RaftNode('id', [], lambda x: None)
    node._log('DEBUG', 'd')
    node._log('INFO', 'i')
    node._log('WARNING', 'w')
    node._log('ERROR', 'e')
    assert ('DEBUG', 'd') in dummy.msgs
    assert ('INFO', 'i') in dummy.msgs
    assert ('WARNING', 'w') in dummy.msgs
    assert ('ERROR', 'e') in dummy.msgs


def test_handle_request_vote_lower_term(node):
    node.current_term = 5
    req = raft_pb2.RequestVoteRequest(term=4, candidate_id='c', last_log_index=0, last_log_term=0)
    resp = node.handle_request_vote(req, None)
    assert resp.term == 5
    assert not resp.vote_granted


def test_handle_request_vote_grant(node):
    # Default current_term=0, empty log
    req = raft_pb2.RequestVoteRequest(term=0, candidate_id='c1', last_log_index=0, last_log_term=0)
    resp = node.handle_request_vote(req, None)
    assert resp.term == 0
    assert resp.vote_granted
    assert node.voted_for == 'c1'


def test_handle_append_entries_reject_lower_term(node):
    node.current_term = 2
    req = raft_pb2.AppendEntriesRequest(term=1, leader_id='l', prev_log_index=-1, prev_log_term=0, entries=[], leader_commit=0)
    resp = node.handle_append_entries(req, None)
    assert resp.term == 2
    assert not resp.success


def test_handle_append_entries_append_and_commit(node, dummy_callback):
    calls, _ = dummy_callback
    node.current_term = 1
    # Append entry with term=1
    entry = raft_pb2.LogEntry(term=1, command='cmd1')
    req = raft_pb2.AppendEntriesRequest(
        term=1, leader_id='l', prev_log_index=-1, prev_log_term=0,
        entries=[entry], leader_commit=0
    )
    resp = node.handle_append_entries(req, None)
    assert resp.success
    # log updated
    assert len(node.log) == 1
    assert node.log[0].command == 'cmd1'
    # commit_index should be 0
    assert node.commit_index == 0
    # callback applied committed entries
    assert 'cmd1' in calls


def test_submit_command_leader(node):
    node.state = 'Leader'
    node.current_term = 3
    ok = node.submit_command('xyz')
    assert ok
    # new log entry exists
    assert node.log and node.log[-1].command == 'xyz'
    assert node.log[-1].term == 3


def test_submit_command_not_leader(node):
    node.state = 'Follower'
    length_before = len(node.log)
    ok = node.submit_command('xyz')
    assert not ok
    assert len(node.log) == length_before
