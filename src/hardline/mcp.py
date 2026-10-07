import asyncio
from pathlib import Path

from matrix_mcp.config import MatrixMCPConfig
from matrix_mcp.matrix_client import MatrixAPIClient

from hardline.locking import serialized
from hardline.runtime import (
    ROOT,
    STATE,
    Codex,
    CodexRejected,
    agents,
    allowed_rooms,
    credential,
    private_write,
    settings,
    worker_config,
)


def thread_relation(source_id, event):
    relation = event.get("content", {}).get("m.relates_to", {})
    root = relation["event_id"] if relation.get("rel_type") == "m.thread" else source_id
    return {
        "rel_type": "m.thread",
        "event_id": root,
        "is_falling_back": False,
        "m.in_reply_to": {"event_id": source_id},
    }


async def source_event(mx, room, event):
    from urllib.parse import quote

    return await mx.call(
        "GET",
        "/_matrix/client/v3/rooms/"
        + quote(room, safe="")
        + "/event/"
        + quote(event, safe=""),
    )


def server(slug):
    registry = agents()
    if slug not in registry:
        raise ValueError("Unknown agent")
    c = credential(slug)

    class ScopedClient(MatrixAPIClient):
        def _resolve_room(self, room):
            resolved = super()._resolve_room(room)
            if resolved not in allowed_rooms(slug):
                raise ValueError("Room outside Hardline grants")
            return resolved

        async def read_thread(self, room_id, thread_id, *, limit=50):
            from hardline.runtime import Matrix

            room = self._resolve_room(room_id)
            event_id = self._resolve_event(thread_id)
            mx = Matrix(slug)
            try:
                event = await source_event(mx, room, event_id)
                root = thread_relation(event_id, event)["event_id"]
            finally:
                await mx.close()
            return await super().read_thread(room, root, limit=limit)

        async def list_rooms(self):
            return [
                r
                for r in await super().list_rooms()
                if r.room_id in allowed_rooms(slug)
            ]

    client = lambda: ScopedClient(MatrixMCPConfig.model_validate(c))
    from matrix_mcp.mcp_server import create_mcp_server

    m = create_mcp_server(client)
    # Remove every upstream tool not included in the approved messaging baseline.
    allowed = {
        "matrix_whoami",
        "matrix_list_rooms",
        "matrix_read_room_recent",
        "matrix_read_thread",
        "matrix_send_message",
        "matrix_get_room_info",
        "matrix_list_room_members",
    }
    for name in asyncio.run(m.list_tools()):
        if name.name not in allowed:
            m.local_provider.remove_tool(name.name)
    # Replace sends with room grants and stable transaction IDs.
    m.local_provider.remove_tool("matrix_send_message")

    @m.tool
    async def matrix_send_message(
        room_id: str,
        body: str,
        request_id: str,
        mentions: list[str] | None = None,
        thread_id: str | None = None,
    ):
        import hashlib

        from hardline.runtime import Matrix

        if room_id not in allowed_rooms(slug):
            raise ValueError("Room outside Hardline grants")
        if not request_id or len(request_id) > 200:
            raise ValueError("A stable request_id is required")
        from urllib.parse import quote

        mx = Matrix(slug)
        try:
            response = await mx.http.get(
                "/_matrix/client/v3/rooms/"
                + quote(room_id, safe="")
                + "/state/m.room.encryption"
            )
            if response.status_code != 404:
                raise ValueError(
                    "Encrypted room or unverifiable encryption state: send refused"
                )
            if response.json().get("errcode") != "M_NOT_FOUND":
                raise ValueError("Cannot verify room encryption state")
            content = {
                "msgtype": "m.text",
                "body": body,
                "m.mentions": {"user_ids": mentions or []},
            }
            if thread_id:
                event = await source_event(mx, room_id, thread_id)
                content["m.relates_to"] = thread_relation(thread_id, event)
            from hardline.sends import Sends

            ledger = Sends(STATE / "sends.sqlite")
            payload = {"room": room_id, "content": content}
            existing = ledger.reserve(slug, request_id, payload)
            if existing:
                return {"event_id": existing}
            txn = hashlib.sha256((slug + ":" + request_id).encode()).hexdigest()
            result = await mx.call(
                "PUT",
                "/_matrix/client/v3/rooms/"
                + quote(room_id, safe="")
                + "/send/m.room.message/"
                + txn,
                content,
            )
            ledger.complete(slug, request_id, result["event_id"])
            return result
        finally:
            await mx.close()

    # Room membership is fixed by account grants; lifecycle tools require manager grants.
    if slug in settings().get("management_agents", []):

        @m.tool
        def list_agents():
            return agents()

        @m.tool
        def get_agent(agent_id: str):
            return agents()[agent_id]

        @m.tool
        def validate_agent_folder(folder: str):
            path = Path(folder).resolve()
            roots = [Path(x).resolve() for x in settings()["allowed_roots"]]
            if not any(path.is_relative_to(x) for x in roots):
                raise ValueError("Folder outside allowed roots")
            if not all((path / x).is_file() for x in ["AGENTS.md", "EMPLOYEE.md"]):
                raise ValueError("Missing charter files")
            return {"folder": str(path), "valid": True}

        @m.tool
        @serialized
        async def register_agent(agent_id: str, folder: str, request_id: str):
            import re

            if not re.fullmatch("[a-z][a-z0-9-]{0,40}", agent_id):
                raise ValueError("Invalid agent ID")
            path = validate_agent_folder(folder)["folder"]
            r = agents()
            if agent_id in r:
                if r[agent_id]["cwd"] != path:
                    raise ValueError("Agent ID collision")
                if r[agent_id].get("thread_id") or r[agent_id].get("status") in {
                    "creating_thread",
                    "creation_uncertain",
                }:
                    return r[agent_id]
            r[agent_id] = {
                "cwd": path,
                "thread_id": None,
                "status": "awaiting_credentials",
                "request_id": request_id,
                "desktop_project_status": "unavailable",
            }
            private_write(ROOT / "agents.json", r)
            # User supplies credentials outside MCP. Missing credentials is a normal resumable state.
            if not (STATE / "credentials" / f"{agent_id}.json").exists():
                from hardline.provision import provision

                result = await provision(agent_id)
                if result["status"] == "awaiting_credentials":
                    return {
                        "agent_id": agent_id,
                        "status": "awaiting_credentials",
                        "folder": path,
                    }
            install_mcp_config(agent_id, path)
            r[agent_id]["status"] = "creating_thread"
            private_write(ROOT / "agents.json", r)
            attempted = False
            try:
                async with Codex() as cx:
                    attempted = True
                    t = await cx.request(
                        "thread/start",
                        {
                            "cwd": path,
                            "approvalPolicy": "on-request",
                            "config": worker_config(agent_id),
                        },
                    )
            except CodexRejected:
                r[agent_id]["status"] = "registration_failed"
                private_write(ROOT / "agents.json", r)
                raise
            except Exception:
                r[agent_id]["status"] = (
                    "creation_uncertain" if attempted else "registration_failed"
                )
                private_write(ROOT / "agents.json", r)
                raise
            r[agent_id] = {
                "cwd": path,
                "thread_id": t["thread"]["id"],
                "matrix_user": credential(agent_id)["user_id"],
                "status": "paused",
                "request_id": request_id,
                "desktop_project_status": "unavailable",
            }
            private_write(ROOT / "agents.json", r)
            return r[agent_id]

        @m.tool
        @serialized
        async def recover_registration(agent_id: str, thread_id: str):
            """Attach an inspected existing conversation after an uncertain creation; never creates another."""
            r = agents()
            a = r[agent_id]
            if a.get("status") not in {"creation_uncertain", "creating_thread"}:
                raise ValueError("Registration is not awaiting reconciliation")
            if any(
                v.get("thread_id") == thread_id for k, v in r.items() if k != agent_id
            ):
                raise ValueError("Conversation already belongs to another agent")
            async with Codex() as cx:
                thread = (await cx.read(thread_id))["thread"]
            if str(Path(thread["cwd"]).resolve()) != a["cwd"]:
                raise ValueError("Conversation folder does not match registration")
            a.update(
                thread_id=thread_id,
                matrix_user=credential(agent_id)["user_id"],
                status="paused",
            )
            private_write(ROOT / "agents.json", r)
            return a

        @m.tool
        def get_operation_status(request_id: str):
            return [
                dict(agent_id=k, **v)
                for k, v in agents().items()
                if v.get("request_id") == request_id
            ]

        @m.tool
        @serialized
        def pause_agent(agent_id: str):
            r = agents()
            r[agent_id]["status"] = "paused"
            private_write(ROOT / "agents.json", r)
            return {"status": "paused", "active_turn_interrupted": False}

        @m.tool
        @serialized
        def start_agent(agent_id: str):
            r = agents()
            if not r[agent_id].get("thread_id"):
                raise ValueError("Agent registration is incomplete")
            r[agent_id]["status"] = "active"
            cfg = settings()
            if r[agent_id]["matrix_user"] not in cfg["senders"]:
                cfg["senders"].append(r[agent_id]["matrix_user"])
                private_write(STATE / "settings.json", cfg)
            private_write(ROOT / "agents.json", r)
            return {"status": "active"}

    return m


def install_mcp_config(slug, folder):
    import tomllib

    path = Path(folder) / ".codex/config.toml"
    if not path.resolve().is_relative_to(Path(folder).resolve()):
        raise ValueError("MCP configuration path escapes agent folder")
    path.parent.mkdir(exist_ok=True)
    content = path.read_text() if path.exists() else ""
    parsed = tomllib.loads(content)
    if set(parsed) - {"mcp_servers"}:
        raise ValueError("Agent configuration contains non-controller settings")
    if any(
        name != "hardline" and value.get("enabled", True)
        for name, value in parsed.get("mcp_servers", {}).items()
    ):
        raise ValueError("Agent configuration contains a non-baseline MCP launcher")
    if "hardline" in parsed.get("mcp_servers", {}):
        expected = {
            "command": str(ROOT / ".venv/bin/hardline"),
            "args": ["mcp", "--agent", slug],
        }
        if any(
            parsed["mcp_servers"]["hardline"].get(k) != v for k, v in expected.items()
        ) or set(parsed["mcp_servers"]["hardline"]) - {"command", "args", "tools"}:
            raise ValueError(
                "Existing Hardline launch profile does not match agent identity"
            )
        if parsed["mcp_servers"]["hardline"].get("tools"):
            return
    else:
        import json

        content += (
            "\n[mcp_servers.hardline]\ncommand = "
            + json.dumps(str(ROOT / ".venv/bin/hardline"))
            + "\nargs = "
            + json.dumps(["mcp", "--agent", slug])
            + "\n"
        )
    for tool in [
        "matrix_whoami",
        "matrix_list_rooms",
        "matrix_read_room_recent",
        "matrix_read_thread",
        "matrix_send_message",
        "matrix_get_room_info",
        "matrix_list_room_members",
    ]:
        content += f'\n[mcp_servers.hardline.tools.{tool}]\napproval_mode = "approve"\n'
    path.write_text(content)
