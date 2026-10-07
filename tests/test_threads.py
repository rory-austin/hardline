from hardline.mcp import thread_relation


def test_followup_reply_uses_original_thread_root():
    event = {
        "content": {
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": "$root",
                "m.in_reply_to": {"event_id": "$earlier"},
            }
        }
    }
    assert thread_relation("$followup", event) == {
        "rel_type": "m.thread",
        "event_id": "$root",
        "is_falling_back": False,
        "m.in_reply_to": {"event_id": "$followup"},
    }


def test_first_reply_creates_thread_on_source():
    assert thread_relation("$source", {"content": {}})["event_id"] == "$source"
