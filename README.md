# Hardline

A local bridge between Matrix chat and persistent Codex agents. Matrix messages wake agents; Hardline handles routing, lifecycle, scoped messaging tools, and durable delivery state. A designated manager agent can register and pause other agents through MCP.

**Experimental alpha.** This is a working personal deployment made shareable, not a turnkey hosted service. It currently targets a Unix host with a local Codex app-server daemon. The managed-controller integration was tested with Codex 0.159.2; compatibility with other versions requires verification. Windows and other agent runtimes are not supported yet.

## What is Matrix?

[Matrix](https://matrix.org/) is an open standard for decentralized messaging. A **homeserver** hosts accounts and chat rooms; a compatible client, such as [Element](https://element.io/), is the app you use to chat. You can host your own homeserver or use one provided by someone else. Accounts and rooms can communicate across servers when federation is enabled.

Hardline gives agents Matrix identities and turns messages into work in their persistent Codex conversations. You use an ordinary chat app to talk to your agents. Matrix supports encrypted messaging, but Hardline's current agent transport requires unencrypted rooms.

## Useful scenarios

- **Reach agents on your main machine while away.** Send a request from your phone or another computer through Matrix, much as you might use Codex Remote to continue work remotely. The agent works with the tools and files on its host. That host must stay awake, connected, and running Hardline.
- **Message agents on another machine.** Run Hardline and its controlled Codex instance on that machine, then message its agents from your usual Matrix client. Each installation manages its own local agents; Matrix carries messages between people and agents across machines.
- **Let trusted people request work from your agents.** Allowlist their exact Matrix identities and grant access to designated rooms. For example, a family member can ask a document agent to retrieve an approved statement without receiving your Codex login or remote desktop connection. Define requester authority and disclosure limits in the agent's charter.
- **Offer a narrowly scoped service to a wider group.** Give a documentation, project-status, or support agent a clear charter, restricted tool and folder access, and a specific set of requesters. Start with explicitly enrolled users. A charter alone is not a security sandbox; this alpha does not provide anonymous public access, tenant isolation, or a complete abuse-control system.
- **Let agents coordinate with one another.** Give agents separate identities and scoped rooms so they can request help, hand off work, and reply in shared threads while retaining distinct responsibilities.

Matrix is the task and conversation interface. A [Codex remote connection](docs/remote-access.md) provides direct inspection, debugging, and native approval handling for the controlled instance. Trusted Matrix participants do not need that administrative connection.

## Codex usage and cost

When the controlled Codex instance is signed in with your **ChatGPT account**, its model/token usage draws from your existing plan's included Codex allowance. Hardline does not make a separate model API call or add its own token charge. All your Hardline agents use the allowance of the account running that controller; another person's Matrix request does not transfer usage to their ChatGPT account.

Normal plan limits and any credit or workspace billing rules still apply: this is not unlimited usage or a separate allowance per agent or Codex home. If you authenticate Codex with an **API key**, that usage is billed separately at API rates. Matrix hosting and any paid third-party tools may have their own costs. See [OpenAI's current Codex pricing and usage documentation](https://learn.chatgpt.com/docs/pricing) and [authentication documentation](https://learn.chatgpt.com/docs/auth).

## What it does

- Wake an agent on a Matrix mention, configured alias, assigned thread reply, or designated private-room message.
- Wrap seven Matrix messaging tools with per-agent room grants and stable send request IDs.
- Give designated managers lifecycle tools: list/get agents, validate/register folders, start/pause, operation status, and registration recovery.
- Queue busy agents, coalesce bursts, cap concurrent turns and thread hops, and reconcile uncertain delivery against conversation history.
- Keep account credentials outside MCP arguments. Optionally provision non-admin Matrix identities over SSH, or accept supplied credentials.
- Leave Codex approval requests for the human. The listener never approves tools on the user's behalf.

## Requirements

Python 3.12+, [uv](https://docs.astral.sh/uv/), a compatible Codex CLI/daemon authenticated to your account, and a Matrix homeserver with a dedicated listener account and separate agent accounts. Coordination rooms must be **unencrypted**: this wrapper does not implement end-to-end encryption.

## Setup

Clone the repository, enter it, and run:

```sh
uv sync --locked --group dev
export HARDLINE_HOME="$PWD"
# Set this if the compatible Codex executable is not bundled on macOS or on PATH:
# export HARDLINE_CODEX_CLI=/absolute/path/to/codex
mkdir -p .runtime/credentials
chmod 700 .runtime .runtime/credentials
cp examples/settings.json .runtime/settings.json
cp examples/agents.json agents.json
chmod 600 .runtime/settings.json agents.json
```

Edit these private files before starting. Replace every example room, sender, account, allowed agent-folder root, and conversation ID with your own. Each agent folder needs `AGENTS.md` and `EMPLOYEE.md`; write a charter that defines its actual task authority. Hardline does not create charters or bootstrap the manager's project automatically.

Create each account on your homeserver and import its token from a private JSON file shaped like `examples/credentials.json`:

```sh
uv run hardline import-credentials listener --file /private/path/listener.json
uv run hardline import-credentials manager --file /private/path/manager.json
```

The listener must join every monitored room; each agent must join its own granted rooms. Account creation does not imply room membership. Never commit real credential files.

Start the controller with its own Codex home:

```sh
CODEX_HOME="$HARDLINE_HOME/.runtime/codex-home" codex remote-control start --json
```

Use the same CLI selected for Hardline and authenticate that controlled home first. `HARDLINE_HOME` must also be available to the managed daemon and its MCP subprocesses. If a daemon predates that environment setting, configure its service environment and restart it while agents are idle.

Bootstrap the manager conversation using the supported app-server API (`thread/start`, then `turn/start`) or a client connected to this controller. **Send an initial message and confirm the conversation is saved and resumable before recording its ID in `agents.json`.** Merely creating an empty conversation can leave a non-resumable entry after a daemon restart. Agent registration currently shares that limitation; initialize newly registered chats before relying on them after restart.

For direct inspection and native approvals, [pair your primary desktop app with this controller](docs/remote-access.md).

Then run:

```sh
uv run hardline status
uv run hardline run --once
uv run hardline run
```

The first sync establishes a baseline; it deliberately does not replay the room's old history. Send a new message mentioning the agent after startup. Keep the foreground process running, or install a service using the [service guide](docs/services.md).

## Configuration

`HARDLINE_HOME` is the controller checkout root; it contains the private `agents.json` registry and `.runtime/` directory. Without the variable, source-checkout execution uses the source tree root. Wheel installations require an explicit `HARDLINE_HOME` and a controller virtual environment with `.venv/bin/hardline`.

`settings.json` fields:

| Field | Meaning |
| --- | --- |
| `homeserver` | Matrix client URL |
| `rooms` | Shared room IDs granted to all enrolled agents |
| `senders` | Exact Matrix user IDs permitted to trigger work |
| `management_agents` | Agent IDs receiving lifecycle tools |
| `allowed_roots` | Absolute roots under which managers may register agent folders |
| `agent_rooms` | Agent ID → additional private room IDs |
| `direct_rooms` | Private room ID → owning agent ID; authorized messages wake it without mentions |
| `agent_write_paths` | Agent ID → explicitly approved filesystem write paths |
| `provisioning` | `supplied` (default example) or configured `ssh` mode |

The registry maps agent IDs to absolute `cwd`, saved `thread_id`, `matrix_user`, and `status` (`active` or `paused`). Optional `mention_aliases` allow short names such as `helper` to match `@helper`. Use unique aliases. Pausing stops future routing without interrupting an accepted turn.

## Optional SSH provisioning

This mode is specific to Docker-based Synapse deployments. Configure `provisioning.mode="ssh"`, `host`, `known_hosts`, and `admin_credentials_file` (a private **remote** JSON containing `username` and `password`). Optional remote paths: `staging_directory`, `synapse_config`, and `synapse_container`. Defaults are `/var/lib/hardline/provisioning`, `/matrix/synapse/config/homeserver.yaml`, and `matrix-synapse`.

The SSH account needs permission to run the provisioning Python script through `sudo`, inspect Docker, and read Synapse configuration. PyYAML must be available on the server. Shared-secret registration must be configured. Admin and registration secrets stay on the server; newly created accounts are non-admin. This adapter has the SSH key's host privileges: it is trusted controller infrastructure, not an agent sandbox. Publicly exposing Synapse's admin API is unnecessary.

In supplied mode, registration waits at `awaiting_credentials`; import the private credential file and retry the same registration request. Human accounts are not a dedicated MCP workflow.

## Boundaries and recovery

See [SECURITY.md](SECURITY.md). Matrix content remains untrusted task input. A sender allowlist is not a replacement for a scoped agent charter or human approval. Installed plugins and account connections may be shared with your desktop account; a separate Codex home does not guarantee security isolation.

Private queue files retain message references and sync cursors, not full bodies. A separate send ledger retains payload digests and event IDs. `uncertain` deliveries are not blindly repeated. `recover_registration` attaches an inspected existing chat after validating folder ownership; it does not create a duplicate. Startup diagnostics contain error types rather than credential payloads.

Desktop sidebar project creation is unavailable. Use Hardline's registry for lifecycle inventory and a supported controller client for approvals. Matrix-delivered native Codex approvals, encrypted rooms, direct control of nonlocal agent runtimes from a single controller, and plugin packaging remain future work. Ketesa, homeserver installation, and personal administration scripts are not part of this repository.

## Development

```sh
uv sync --locked --group dev
uv run pytest -q
uvx ruff check src tests
uv build
```

Tests use synthetic identities and isolated settings. A passing suite is not proof that your Matrix homeserver or Codex version is compatible; perform a scoped end-to-end test in your own deployment.

## License

MIT. Third-party dependencies retain their own licenses; see their upstream projects. Matrix MCP is a separately installed dependency, not vendored code.
