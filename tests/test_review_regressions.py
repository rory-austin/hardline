import pytest

from hardline.core import Queue
from hardline.mcp import install_mcp_config
from hardline.runner import capture_batch, delivered_ref


def test_rejects_management_identity(tmp_path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text(
        '[mcp_servers.hardline]\ncommand="bad"\nargs=["mcp","--agent","manager"]\n'
    )
    with pytest.raises(ValueError, match="launch profile"):
        install_mcp_config("helper", tmp_path)


def test_same_batch_thread_assignment(tmp_path):
    q = Queue(tmp_path / "q.sqlite")

    def event(eid, body, root=None):
        content = {"msgtype": "m.text", "body": body}
        if root:
            content["m.relates_to"] = {"rel_type": "m.thread", "event_id": root}
        return {
            "event_id": eid,
            "type": "m.room.message",
            "sender": "@human:x",
            "content": content,
        }

    registry = {"helper": {"status": "active", "matrix_user": "@helper:x"}}
    cfg = {"rooms": ["!r"], "senders": ["@human:x"]}
    sync = {
        "rooms": {
            "join": {
                "!r": {
                    "timeline": {
                        "events": [
                            event("$one", "@helper:x work"),
                            event("$two", "more work", "$one"),
                        ]
                    }
                }
            }
        }
    }
    result = capture_batch(q, sync, registry, cfg)
    assert [x[0] for x in result] == ["$one", "$two"]
    q.capture(result, "cursor")
    # Agent first mentioned inside somebody else's existing thread.
    sync["rooms"]["join"]["!r"]["timeline"]["events"] = [
        event("$three", "@helper:x help", "$external")
    ]
    q.capture(capture_batch(q, sync, registry, cfg), "cursor2")
    sync["rooms"]["join"]["!r"]["timeline"]["events"] = [
        event("$four", "followup", "$external")
    ]
    assert capture_batch(q, sync, registry, cfg)[0][0] == "$four"


def test_event_prefix_cannot_reconcile():
    t = {
        "turns": [
            {
                "id": "t",
                "items": [
                    {
                        "type": "userMessage",
                        "content": [
                            {
                                "type": "text",
                                "text": "Hardline routed Matrix events $one2 in room !r.",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    assert delivered_ref(t, "$one") is None


def test_registration_failure_and_recovery(tmp_path, monkeypatch):
    import asyncio

    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    from hardline import locking, mcp
    from hardline.runtime import CodexRejected

    folder = tmp_path / "helper"
    folder.mkdir()
    for name in ["AGENTS.md", "EMPLOYEE.md"]:
        (folder / name).write_text("Charter")
    state = tmp_path / "state"
    (state / "credentials").mkdir(parents=True)
    (state / "credentials/helper.json").write_text("{}")
    registry = {"manager": {}}
    monkeypatch.setattr(mcp, "STATE", state)
    monkeypatch.setattr(locking, "STATE", state)
    monkeypatch.setattr(mcp, "agents", lambda: registry)
    monkeypatch.setattr(
        mcp,
        "settings",
        lambda: {"allowed_roots": [str(tmp_path)], "management_agents": ["manager"]},
    )
    monkeypatch.setattr(
        mcp,
        "credential",
        lambda slug: {
            "homeserver": "https://example.org",
            "user_id": "@" + slug + ":example.org",
            "access_token": "fixture",
        },
    )
    monkeypatch.setattr(mcp, "private_write", lambda p, data: registry.update(data))
    monkeypatch.setattr(mcp, "install_mcp_config", lambda *a: None)

    class FakeCodex:
        mode = "reject"
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def request(self, *a):
            self.__class__.calls += 1
            if self.mode == "reject":
                raise CodexRejected("rejected")
            raise TimeoutError("lost response")

        async def read(self, tid):
            return {"thread": {"cwd": str(folder)}}

    monkeypatch.setattr(mcp, "Codex", FakeCodex)
    server = mcp.server("manager")

    async def run():
        async with Client(server) as c:
            args = {"agent_id": "helper", "folder": str(folder), "request_id": "retry"}
            with pytest.raises(ToolError):
                await c.call_tool("register_agent", args)
            assert registry["helper"]["status"] == "registration_failed"
            FakeCodex.mode = "timeout"
            with pytest.raises(ToolError):
                await c.call_tool("register_agent", args)
            assert registry["helper"]["status"] == "creation_uncertain"
            await c.call_tool("register_agent", args)
            assert FakeCodex.calls == 2
            recovered = await c.call_tool(
                "recover_registration", {"agent_id": "helper", "thread_id": "existing"}
            )
            assert recovered.data["thread_id"] == "existing"
            assert recovered.data["status"] == "paused"

    asyncio.run(run())


def test_rejects_other_mcp_launchers_and_sandbox_override(tmp_path):
    (tmp_path / ".codex").mkdir()
    path = tmp_path / ".codex/config.toml"
    path.write_text(
        '[mcp_servers.other]\ncommand="hardline"\nargs=["mcp","--agent","manager"]\n'
    )
    with pytest.raises(ValueError, match="non-baseline"):
        install_mcp_config("helper", tmp_path)
    path.write_text('sandbox_mode="danger-full-access"\n')
    with pytest.raises(ValueError, match="non-controller"):
        install_mcp_config("helper", tmp_path)


def test_initiator_receives_unmentioned_reply(tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    registry = {
        "helper": {"status": "active", "matrix_user": "@helper:x"},
        "manager": {"status": "active", "matrix_user": "@manager:x"},
    }
    cfg = {"rooms": ["!r"], "senders": ["@helper:x", "@manager:x"]}
    events = [
        {
            "event_id": "$root",
            "type": "m.room.message",
            "sender": "@helper:x",
            "content": {"msgtype": "m.text", "body": "@manager:x do work"},
        },
        {
            "event_id": "$reply",
            "type": "m.room.message",
            "sender": "@manager:x",
            "content": {
                "msgtype": "m.text",
                "body": "Work complete",
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$root"},
            },
        },
    ]
    sync = {"rooms": {"join": {"!r": {"timeline": {"events": events}}}}}
    q.capture(capture_batch(q, sync, registry, cfg), "cursor")
    assert set(q.pending()) == {("$root", "manager", "!r"), ("$reply", "helper", "!r")}
