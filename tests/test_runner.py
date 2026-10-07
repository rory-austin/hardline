from hardline.runner import active_turn, delivered_ref


def test_busy_and_reconciliation():
    assert active_turn({"turns": [{"status": "inProgress"}]})
    assert not active_turn({"turns": [{"status": "completed"}]})
    t = {
        "turns": [
            {
                "id": "turn1",
                "items": [
                    {
                        "type": "userMessage",
                        "content": [
                            {
                                "type": "text",
                                "text": "Hardline routed Matrix event $one in room !r",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    assert delivered_ref(t, "$one") == "turn1"
    assert delivered_ref(t, "$two") is None


def test_not_loaded_can_resume_approval_cannot():
    assert not active_turn({"status": {"type": "notLoaded"}, "turns": []})
    assert active_turn(
        {
            "status": {"type": "active", "activeFlags": ["waitingOnApproval"]},
            "turns": [],
        }
    )


def test_approval_notice_survives_restart_without_repeat(tmp_path):
    import asyncio

    from hardline.core import Queue
    from hardline.runner import notify_approval

    q = Queue(tmp_path / "q")
    q.capture([("$followup", "neo", "!room", "$root")], "cursor")
    q.mark("$followup", "delivered", "turn", owner="neo")

    class Matrix:
        def __init__(self):
            self.calls = []

        async def call(self, *args):
            self.calls.append(args)
            return {"event_id": "$notice"}

    mx = Matrix()
    thread = {
        "status": {"type": "active", "activeFlags": ["waitingOnApproval"]},
        "turns": [{"id": "turn", "status": "inProgress"}],
    }

    async def run():
        assert await notify_approval(q, mx, "neo", thread)
        assert await notify_approval(Queue(tmp_path / "q"), mx, "neo", thread)
        assert len(mx.calls) == 1
        assert mx.calls[0][2]["m.relates_to"]["event_id"] == "$root"

    asyncio.run(run())


def test_private_direct_room_routes_only_owner_without_mention(tmp_path):
    from hardline.core import Queue
    from hardline.runner import capture_batch

    q = Queue(tmp_path / "q")
    registry = {
        "tim": {"status": "active", "matrix_user": "@tim:x"},
        "bob": {"status": "active", "matrix_user": "@bob:x"},
    }
    cfg = {
        "rooms": ["!shared"],
        "agent_rooms": {"tim": ["!dm"]},
        "direct_rooms": {"!dm": "tim"},
        "senders": ["@owner:x"],
    }
    event = {
        "event_id": "$request",
        "sender": "@owner:x",
        "type": "m.room.message",
        "content": {"msgtype": "m.text", "body": "Please test access"},
    }
    sync = {"rooms": {"join": {"!dm": {"timeline": {"events": [event]}}}}}
    assert capture_batch(q, sync, registry, cfg) == [
        ("$request", "tim", "!dm", "$request")
    ]
    event["content"]["body"] = "@bob please test access"
    assert capture_batch(q, sync, registry, cfg) == [
        ("$request", "tim", "!dm", "$request")
    ]


def test_room_grants_are_agent_specific():
    from hardline.runtime import allowed_rooms

    cfg = {"rooms": ["!shared"], "agent_rooms": {"tim": ["!dm"]}}
    assert allowed_rooms("tim", cfg) == {"!shared", "!dm"}
    assert allowed_rooms("bob", cfg) == {"!shared"}
