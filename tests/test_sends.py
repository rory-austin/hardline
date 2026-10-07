import pytest

from hardline.sends import Sends


def test_send_ledger_replay_and_conflict(tmp_path):
    s = Sends(tmp_path / "sends")
    c = {"room": "!r", "content": {"body": "hello"}}
    assert s.reserve("bob", "request", c) is None
    s.complete("bob", "request", "$event")
    assert Sends(tmp_path / "sends").reserve("bob", "request", c) == "$event"
    with pytest.raises(ValueError):
        s.reserve("bob", "request", {"body": "different"})
    assert s.reserve("neo", "request", c) is None
