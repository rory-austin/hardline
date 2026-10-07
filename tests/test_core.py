from hardline.core import Queue, eligible


def event(
    sender="@human:example.org",
    body="hello @helper:example.org",
    kind="m.room.message",
):
    return {
        "event_id": "$one",
        "sender": sender,
        "type": kind,
        "content": {"body": body, "msgtype": "m.text"},
    }


def test_routing():
    assert eligible(event(), "@helper:example.org", {"@human:example.org"})
    assert not eligible(
        event(sender="@helper:example.org"),
        "@helper:example.org",
        {"@helper:example.org"},
    )
    assert not eligible(
        event(body="hello Helper"), "@helper:example.org", {"@human:example.org"}
    )
    assert not eligible(
        event(kind="m.reaction"), "@helper:example.org", {"@human:example.org"}
    )
    e = event()
    e["content"]["m.relates_to"] = {"rel_type": "m.replace"}
    assert not eligible(e, "@helper:example.org", {"@human:example.org"})


def test_atomic_cursor_dedup_restart(tmp_path):
    p = tmp_path / "queue.sqlite"
    q = Queue(p)
    q.capture([("$one", "helper", "!room")], "s1")
    q.capture([("$one", "helper", "!room")], "s2")
    assert len(q.pending()) == 1
    assert q.cursor() == "s2"
    q.mark("$one", "delivered")
    assert Queue(p).pending() == []


def test_thread_reply_and_ack():
    e = event(body="Please check the next step")
    e["content"]["m.relates_to"] = {"rel_type": "m.thread", "event_id": "$root"}
    assert eligible(e, "@helper:example.org", {"@human:example.org"}, {"$root"})
    assert not eligible(
        event(body="@helper:example.org thanks!"),
        "@helper:example.org",
        {"@human:example.org"},
    )


def test_uncertain_is_not_retried(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([("$a", "helper", "!r")], "s")
    q.mark("$a", "uncertain")
    assert q.pending() == []


def test_one_message_can_address_two_agents(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([("$a", "helper", "!r"), ("$a", "manager", "!r")], "s")
    q.mark("$a", "delivered", owner="helper")
    assert q.pending() == [("$a", "manager", "!r")]


def test_conversation_hop_limit(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([(f"${i}", "helper", "!r", "$root") for i in range(25)], "s")
    assert len(q.pending()) == 20
    assert (
        q.db.execute(
            "SELECT count(*) FROM events WHERE status='loop_limit'"
        ).fetchone()[0]
        == 5
    )


def test_short_agent_mentions():
    user = "@manager:example.org"

    def event(body):
        return {
            "event_id": "$short",
            "type": "m.room.message",
            "sender": "@human:example.org",
            "content": {"msgtype": "m.text", "body": body},
        }

    for text in [
        "@manager who are you?",
        "Hello @manager, can you help?",
        "@Manager help me",
    ]:
        assert eligible(event(text), user, {"@human:example.org"})
    for text in [
        "@managerial help",
        "@manager:other.example help",
        "manager help",
        "@manager-other help",
    ]:
        assert not eligible(event(text), user, {"@human:example.org"})


def test_configured_alias_routes_without_relaxing_sender_checks():
    user = "@assistant-long-id:example.org"
    senders = {"@human:example.org"}
    assert eligible(
        event(body="@assistant can you test access"),
        user,
        senders,
        aliases=["assistant"],
    )
    assert not eligible(
        event(body="@assistant-extra test access"), user, senders, aliases=["assistant"]
    )
    assert not eligible(
        event(sender="@stranger:elsewhere", body="@assistant test access"),
        user,
        senders,
        aliases=["assistant"],
    )
