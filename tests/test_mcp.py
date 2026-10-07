import asyncio

from hardline import mcp


def test_agent_roles(monkeypatch):
    monkeypatch.setattr(mcp, "settings", lambda: {"management_agents": ["neo"]})
    monkeypatch.setattr(mcp, "agents", lambda: {"neo": {}, "bob": {}})
    monkeypatch.setattr(
        mcp,
        "credential",
        lambda slug: {
            "homeserver": "https://example.org",
            "user_id": "@" + slug + ":example.org",
            "access_token": "fixture",
        },
    )
    for slug in ["neo", "bob"]:
        s = mcp.server(slug)
        names = {x.name for x in asyncio.run(s.list_tools())}
        assert ("register_agent" in names) == (slug == "neo")
        assert "matrix_send_message" in names
        assert "matrix_redact_event" not in names
        assert "matrix_invite_user" not in names


def test_supplied_mode_waits_for_credentials(tmp_path, monkeypatch):
    from fastmcp import Client

    from hardline import locking, provision

    folder = tmp_path / "agents" / "helper"
    folder.mkdir(parents=True)
    (folder / "AGENTS.md").write_text("Helper")
    (folder / "EMPLOYEE.md").write_text("Charter")
    registry = {"neo": {}}
    monkeypatch.setattr(mcp, "agents", lambda: registry)
    monkeypatch.setattr(
        mcp,
        "credential",
        lambda slug: {
            "homeserver": "https://example.org",
            "user_id": "@neo:example.org",
            "access_token": "fixture",
        },
    )
    monkeypatch.setattr(
        mcp,
        "settings",
        lambda: {
            "allowed_roots": [str(tmp_path / "agents")],
            "management_agents": ["neo"],
        },
    )
    monkeypatch.setattr(
        provision, "settings", lambda: {"provisioning": {"mode": "supplied"}}
    )
    monkeypatch.setattr(mcp, "STATE", tmp_path / "state")
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(locking, "STATE", tmp_path / "state")
    monkeypatch.setattr(mcp, "private_write", lambda p, d: registry.update(d))
    server = mcp.server("neo")

    async def run():
        async with Client(server) as c:
            r = await c.call_tool(
                "register_agent",
                {
                    "agent_id": "helper",
                    "folder": str(folder),
                    "request_id": "test-supplied",
                },
            )
            assert r.data["status"] == "awaiting_credentials"
            assert registry["helper"]["thread_id"] is None

    asyncio.run(run())


def test_manager_policy_matches_existing_lifecycle_grant(monkeypatch):
    from hardline import runtime

    monkeypatch.setattr(runtime, "settings", lambda: {"management_agents": ["neo"]})
    neo = runtime.worker_config("neo")["mcp_servers.hardline"]["tools"]
    bob = runtime.worker_config("bob")["mcp_servers.hardline"]["tools"]
    assert neo["register_agent"]["approval_mode"] == "approve"
    assert neo["list_agents"]["approval_mode"] == "approve"
    assert "register_agent" not in bob
