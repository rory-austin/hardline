import pytest

from hardline.sends import Sends


def test_send_ledger_replay_and_conflict(tmp_path):
    s = Sends(tmp_path / "sends")
    c = {"room": "!r", "content": {"body": "hello"}}
    assert s.reserve("helper", "request", c) is None
    s.complete("helper", "request", "$event")
    assert Sends(tmp_path / "sends").reserve("helper", "request", c) == "$event"
    with pytest.raises(ValueError):
        s.reserve("helper", "request", {"body": "different"})
    assert s.reserve("manager", "request", c) is None
