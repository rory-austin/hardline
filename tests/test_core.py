from hardline.core import Queue, eligible


def event(
    sender="@human:example.org",
    body="hello @bob:example.org",
    kind="m.room.message",
):
    return {
        "event_id": "$one",
        "sender": sender,
        "type": kind,
        "content": {"body": body, "msgtype": "m.text"},
    }


def test_routing():
    assert eligible(event(), "@bob:example.org", {"@human:example.org"})
    assert not eligible(
        event(sender="@bob:example.org"),
        "@bob:example.org",
        {"@bob:example.org"},
    )
    assert not eligible(
        event(body="hello Bob"), "@bob:example.org", {"@human:example.org"}
    )
    assert not eligible(
        event(kind="m.reaction"), "@bob:example.org", {"@human:example.org"}
    )
    e = event()
    e["content"]["m.relates_to"] = {"rel_type": "m.replace"}
    assert not eligible(e, "@bob:example.org", {"@human:example.org"})


def test_atomic_cursor_dedup_restart(tmp_path):
    p = tmp_path / "queue.sqlite"
    q = Queue(p)
    q.capture([("$one", "bob", "!room")], "s1")
    q.capture([("$one", "bob", "!room")], "s2")
    assert len(q.pending()) == 1
    assert q.cursor() == "s2"
    q.mark("$one", "delivered")
    assert Queue(p).pending() == []


def test_thread_reply_and_ack():
    e = event(body="Please check the next step")
    e["content"]["m.relates_to"] = {"rel_type": "m.thread", "event_id": "$root"}
    assert eligible(e, "@bob:example.org", {"@human:example.org"}, {"$root"})
    assert not eligible(
        event(body="@bob:example.org thanks!"),
        "@bob:example.org",
        {"@human:example.org"},
    )


def test_uncertain_is_not_retried(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([("$a", "bob", "!r")], "s")
    q.mark("$a", "uncertain")
    assert q.pending() == []


def test_one_message_can_address_two_agents(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([("$a", "bob", "!r"), ("$a", "neo", "!r")], "s")
    q.mark("$a", "delivered", owner="bob")
    assert q.pending() == [("$a", "neo", "!r")]


def test_conversation_hop_limit(tmp_path):
    q = Queue(tmp_path / "q")
    q.capture([(f"${i}", "bob", "!r", "$root") for i in range(25)], "s")
    assert len(q.pending()) == 20
    assert (
        q.db.execute(
            "SELECT count(*) FROM events WHERE status='loop_limit'"
        ).fetchone()[0]
        == 5
    )


def test_short_agent_mentions():
    user = "@neo:example.org"

    def event(body):
        return {
            "event_id": "$short",
            "type": "m.room.message",
            "sender": "@human:example.org",
            "content": {"msgtype": "m.text", "body": body},
        }

    for text in ["@neo who are you?", "Hello @neo, can you help?", "@Neo help me"]:
        assert eligible(event(text), user, {"@human:example.org"})
    for text in [
        "@neon help",
        "@neo:other.example help",
        "neo help",
        "@neo-other help",
    ]:
        assert not eligible(event(text), user, {"@human:example.org"})


def test_configured_alias_routes_without_relaxing_sender_checks():
    user = "@tim-long-id:example.org"
    senders = {"@human:example.org"}
    assert eligible(
        event(body="@tim can you test access"), user, senders, aliases=["tim"]
    )
    assert not eligible(
        event(body="@timothy test access"), user, senders, aliases=["tim"]
    )
    assert not eligible(
        event(sender="@stranger:elsewhere", body="@tim test access"),
        user,
        senders,
        aliases=["tim"],
    )
