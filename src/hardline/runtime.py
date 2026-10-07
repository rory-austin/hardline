import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import httpx
from websockets.asyncio.client import unix_connect

ROOT = (
    Path(os.environ.get("HARDLINE_HOME", Path(__file__).resolve().parents[2]))
    .expanduser()
    .resolve()
)
STATE = ROOT / ".runtime"


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hardline-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def codex_executable():
    explicit = os.environ.get("HARDLINE_CODEX_CLI")
    if explicit:
        return explicit
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
    if bundled.exists():
        return str(bundled)
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("Set HARDLINE_CODEX_CLI to a compatible Codex executable")
    return executable


def settings():
    return json.loads((STATE / "settings.json").read_text())


def agents():
    return json.loads((ROOT / "agents.json").read_text())


def allowed_rooms(slug, cfg=None):
    cfg = settings() if cfg is None else cfg
    return set(cfg["rooms"]) | set(cfg.get("agent_rooms", {}).get(slug, []))


def credential(slug):
    return json.loads((STATE / "credentials" / f"{slug}.json").read_text())


class Matrix:
    def __init__(self, slug):
        self.c = credential(slug)
        self.http = httpx.AsyncClient(
            base_url=self.c["homeserver"],
            headers={"Authorization": "Bearer " + self.c["access_token"]},
            timeout=45,
        )

    async def call(self, method, path, data=None, params=None):
        r = await self.http.request(method, path, json=data, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"Matrix request rejected: HTTP {r.status_code}")
        return r.json()

    async def close(self):
        await self.http.aclose()


class CodexRejected(RuntimeError):
    """An explicit server rejection, safe to retry after correcting its cause."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"Codex request rejected: {code}")


def worker_config(slug=None):
    config = {
        "default_permissions": "hardline-worker",
        "permissions.hardline-worker": {
            "extends": ":workspace",
            "filesystem": {
                ":root": "read",
                str(STATE): "deny",
                str(ROOT): "read",
                str(Path.home() / ".codex"): "deny",
                str(Path.home() / ".ssh"): "deny",
                str(Path.home() / ".config/matrix-mcp"): "deny",
            },
        },
    }
    if slug:
        for path in settings().get("agent_write_paths", {}).get(slug, []):
            config["permissions.hardline-worker"]["filesystem"][path] = "write"
        config["mcp_servers.hardline"] = {
            "command": str(ROOT / ".venv/bin/hardline"),
            "args": ["mcp", "--agent", slug],
            "tools": {
                name: {"approval_mode": "approve"}
                for name in [
                    "matrix_whoami",
                    "matrix_list_rooms",
                    "matrix_read_room_recent",
                    "matrix_read_thread",
                    "matrix_send_message",
                    "matrix_get_room_info",
                    "matrix_list_room_members",
                ]
            },
        }
    if slug and slug in settings().get("management_agents", []):
        for name in [
            "list_agents",
            "get_agent",
            "validate_agent_folder",
            "register_agent",
            "start_agent",
            "pause_agent",
            "get_operation_status",
            "recover_registration",
        ]:
            config["mcp_servers.hardline"]["tools"][name] = {"approval_mode": "approve"}
    return config


class Codex:
    async def __aenter__(self):
        socket = str(STATE / "codex-home/app-server-control/app-server-control.sock")
        try:
            self.ws = await unix_connect(
                socket, uri="ws://localhost", max_size=16 * 1024 * 1024
            )
        except (FileNotFoundError, ConnectionRefusedError):
            process = await asyncio.create_subprocess_exec(
                codex_executable(),
                "remote-control",
                "start",
                "--json",
                env={**os.environ, "CODEX_HOME": str(STATE / "codex-home")},
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), 30)
            if process.returncode:
                raise RuntimeError("Controlled Codex could not start")
            self.ws = await unix_connect(
                socket, uri="ws://localhost", max_size=16 * 1024 * 1024
            )
        self.seq = 0
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "hardline", "version": "0.1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.ws.send(json.dumps({"method": "initialized"}))
        return self

    async def __aexit__(self, *args):
        await self.ws.close()

    async def request(self, method, params):
        self.seq += 1
        rid = self.seq
        await self.ws.send(json.dumps({"id": rid, "method": method, "params": params}))
        while True:
            o = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if o.get("id") == rid and "method" not in o:
                if "error" in o:
                    raise CodexRejected(o["error"].get("code"))
                return o["result"]
            if "id" in o and "method" in o:
                # Never approve on behalf of the user. The desktop connection handles approvals.
                raise RuntimeError("Codex requires user approval; delivery blocked")

    async def read(self, tid):
        try:
            return await self.request(
                "thread/read", {"threadId": tid, "includeTurns": True}
            )
        except CodexRejected as error:
            if error.code != -32601:
                raise
            # Newly created conversations may not yet expose persisted turns.
            # Metadata still exposes busy/approval state; uncertain deliveries stay blocked.
            return await self.request(
                "thread/read", {"threadId": tid, "includeTurns": False}
            )

    async def resume(self, agent):
        return await self.request(
            "thread/resume",
            {
                "threadId": agent["thread_id"],
                "cwd": agent["cwd"],
                "excludeTurns": True,
                "approvalPolicy": "on-request",
                "config": worker_config(
                    next(
                        k
                        for k, a in agents().items()
                        if a["thread_id"] == agent["thread_id"]
                    )
                ),
            },
        )
