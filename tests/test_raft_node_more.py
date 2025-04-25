import pytest
import raft_node
from raft_node import RaftNode
from proto import raft_pb2

@ pytest.fixture(autouse=True)
def disable_threads(monkeypatch):
    # Prevent background election timer and heartbeat threads
    class DummyThread:
        def __init__(self, target=None, daemon=False): pass
        def start(self): pass
    monkeypatch.setattr(raft_node.threading, 'Thread', DummyThread)

@pytest.fixture
def dummy_callback():
    calls = []
    return calls, lambda cmd: calls.append(cmd)


def test_start_election_empty_peers(dummy_callback):
    calls, callback = dummy_callback
    node = RaftNode('node1', [], callback)
    assert node.state == 'Follower'
    assert node.current_term == 0
    node._start_election()
    # State should transition to Candidate with term incremented
    assert node.current_term == 1
    assert node.state == 'Candidate'
    # No peers => next_index and match_index remain empty
    assert node.next_index == {}
    assert node.match_index == {}


def test_become_leader_sets_indexes(dummy_callback):
    calls, callback = dummy_callback
    # Two peers
    peers = [('h1', 1), ('h2', 2)]
    node = RaftNode('id', peers, callback)
    # Simulate candidate with a log entry
    node.state = 'Candidate'
    node.current_term = 2
    node.log = [raft_pb2.LogEntry(term=2, command='cmd')]
    node.peers = ['h1:1', 'h2:2']
    node._become_leader()
    assert node.state == 'Leader'
    # next_index should point after last log index
    assert node.next_index == {'h1:1': 1, 'h2:2': 1}
    # match_index starts at -1
    assert node.match_index == {'h1:1': -1, 'h2:2': -1}


def test_update_commit_index_and_apply(dummy_callback):
    calls, callback = dummy_callback
    node = RaftNode('id', [('h', 1)], callback)
    node.state = 'Leader'
    node.current_term = 1
    # Two entries in log
    node.log = [
        raft_pb2.LogEntry(term=1, command='a'),
        raft_pb2.LogEntry(term=1, command='b'),
    ]
    node.commit_index = -1
    node.last_applied = -1
    # Simulate replication: peer 'h:1' has index 0
    node.match_index = {'h:1': 0}
    node._update_commit_index()
    # Only first entry should be committed
    assert node.commit_index == 0
    # Callback should have applied first command
    assert calls == ['a']


def test_handle_request_vote_various_cases(dummy_callback):
    calls, callback = dummy_callback
    node = RaftNode('id', [], callback)
    node.current_term = 1
    # Case: higher term and up-to-date log
    node.log = [raft_pb2.LogEntry(term=1, command='x')]
    req1 = raft_pb2.RequestVoteRequest(term=2, candidate_id='c', last_log_index=0, last_log_term=1)
    resp1 = node.handle_request_vote(req1, None)
    assert resp1.term == 2 and resp1.vote_granted
    assert node.state == 'Follower' and node.voted_for == 'c'
    # Case: lower term -> rejected
    node = RaftNode('id', [], callback)
    node.current_term = 5
    resp2 = node.handle_request_vote(
        raft_pb2.RequestVoteRequest(term=4, candidate_id='c2', last_log_index=0, last_log_term=0), None)
    assert resp2.term == 5 and not resp2.vote_granted
    # Case: same term, already voted for different -> reject
    node = RaftNode('id', [], callback)
    node.current_term = 3
    node.voted_for = 'other'
    resp3 = node.handle_request_vote(
        raft_pb2.RequestVoteRequest(term=3, candidate_id='c3', last_log_index=0, last_log_term=0), None)
    assert not resp3.vote_granted


def test_handle_append_entries_various(dummy_callback):
    calls, callback = dummy_callback
    node = RaftNode('id', [], callback)
    # Case: reject lower term
    node.current_term = 2
    resp1 = node.handle_append_entries(
        raft_pb2.AppendEntriesRequest(term=1, leader_id='l', prev_log_index=-1, prev_log_term=0, entries=[], leader_commit=0), None)
    assert resp1.term == 2 and not resp1.success
    # Case: higher term -> reset state and success
    node.state = 'Leader'
    resp2 = node.handle_append_entries(
        raft_pb2.AppendEntriesRequest(term=3, leader_id='l', prev_log_index=-1, prev_log_term=0, entries=[], leader_commit=0), None)
    assert node.state == 'Follower' and node.current_term == 3 and resp2.success
    # Case: consistency check fails due to prev_log_index >= len(log)
    node = RaftNode('id', [], callback)
    node.current_term = 1
    node.log = [raft_pb2.LogEntry(term=1, command='x')]
    resp3 = node.handle_append_entries(
        raft_pb2.AppendEntriesRequest(term=1, leader_id='l', prev_log_index=2, prev_log_term=0, entries=[], leader_commit=0), None)
    assert not resp3.success
    # Case: append entries and commit
    node = RaftNode('id', [], callback)
    node.current_term = 1
    # no existing log
    entry = raft_pb2.LogEntry(term=1, command='cmd1')
    resp4 = node.handle_append_entries(
        raft_pb2.AppendEntriesRequest(term=1, leader_id='l', prev_log_index=-1, prev_log_term=0,
                                       entries=[entry], leader_commit=0), None)
    assert resp4.success
    # entry appended
    assert len(node.log) == 1 and node.log[0].command == 'cmd1'
    # commit_index updated
    assert node.commit_index == 0
    # callback applied
    assert calls[-1] == 'cmd1'
