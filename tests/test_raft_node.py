import pytest
from raft_node import RaftNode
from proto import raft_pb2

def test_request_vote_reject_lower_term():
    node = RaftNode("1:1", [], lambda cmd: None)
    node.current_term = 5
    req = raft_pb2.RequestVoteRequest(term=4, candidate_id="2:2", last_log_index=0, last_log_term=0)
    resp = node.handle_request_vote(req, None)
    assert resp.term == 5
    assert not resp.vote_granted
    assert node.state == "Follower"


def test_request_vote_grant_and_record_vote():
    node = RaftNode("1:1", [], lambda cmd: None)
    req = raft_pb2.RequestVoteRequest(term=1, candidate_id="2:2", last_log_index=0, last_log_term=0)
    resp = node.handle_request_vote(req, None)
    assert resp.term == 1
    assert resp.vote_granted
    assert node.voted_for == "2:2"
    assert node.current_term == 1


def test_request_vote_deny_if_already_voted():
    node = RaftNode("1:1", [], lambda cmd: None)
    node.current_term = 1
    node.voted_for = "2:2"
    req = raft_pb2.RequestVoteRequest(term=1, candidate_id="3:3", last_log_index=0, last_log_term=0)
    resp = node.handle_request_vote(req, None)
    assert resp.term == 1
    assert not resp.vote_granted
    assert node.voted_for == "2:2"


def test_append_entries_reject_lower_term():
    node = RaftNode("1:1", [], lambda cmd: None)
    node.current_term = 2
    req = raft_pb2.AppendEntriesRequest(
        term=1, leader_id="2:2", prev_log_index=-1,
        prev_log_term=0, entries=[], leader_commit=0)
    resp = node.handle_append_entries(req, None)
    assert resp.term == 2
    assert not resp.success


def test_append_entries_accept_higher_term_and_reset_state():
    node = RaftNode("1:1", [], lambda cmd: None)
    node.current_term = 0
    node.state = "Candidate"
    req = raft_pb2.AppendEntriesRequest(
        term=1, leader_id="2:2", prev_log_index=-1,
        prev_log_term=0, entries=[], leader_commit=0)
    resp = node.handle_append_entries(req, None)
    assert resp.term == 1
    assert resp.success
    assert node.state == "Follower"
    assert node.current_term == 1


def test_apply_committed_entries_calls_callback():
    applied = []
    def callback(cmd): applied.append(cmd)
    node = RaftNode("1:1", [], callback)
    class Entry:
        pass
    e1 = Entry(); e1.term = 1; e1.command = "cmd1"
    e2 = Entry(); e2.term = 1; e2.command = "cmd2"
    node.log = [e1, e2]
    node.commit_index = 1
    node.last_applied = -1
    node._apply_committed_entries()
    assert applied == ["cmd1", "cmd2"]
    assert node.last_applied == 1
