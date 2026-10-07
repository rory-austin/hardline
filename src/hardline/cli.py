import argparse
import asyncio
import json
from pathlib import Path

from hardline.runtime import STATE, agents, private_write


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    m = s.add_parser("mcp")
    m.add_argument("--agent", required=True)
    r = s.add_parser("run")
    r.add_argument("--once", action="store_true")
    s.add_parser("status")
    i = s.add_parser("import-credentials")
    i.add_argument("agent")
    i.add_argument("--file", required=True)
    args = p.parse_args()
    if args.cmd == "mcp":
        from hardline.mcp import server

        server(args.agent).run()
    elif args.cmd == "run":
        from hardline.locking import lock
        from hardline.runner import run

        with lock("listener"):
            asyncio.run(run(args.once))
    elif args.cmd == "status":
        print(
            json.dumps(
                {
                    "agents": agents(),
                    "listener": json.loads((STATE / "listener-status.json").read_text())
                    if (STATE / "listener-status.json").exists()
                    else {"status": "not_started"},
                },
                indent=2,
            )
        )
    elif args.cmd == "import-credentials":
        import re

        if not re.fullmatch("[a-z][a-z0-9-]{0,40}", args.agent):
            p.error("Invalid agent ID")
        c = json.loads(Path(args.file).read_text())
        from matrix_mcp.config import MatrixMCPConfig

        MatrixMCPConfig.model_validate(c)
        if not c.get("user_id") or not c.get("access_token"):
            p.error("Missing user ID/token")
        private_write(STATE / "credentials" / f"{args.agent}.json", c)
        print("Credentials imported privately.")


if __name__ == "__main__":
    main()
