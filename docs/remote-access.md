# Connect your primary desktop app to the Hardline controller

Hardline normally receives tasks through Matrix. A Codex remote connection lets the operator open the controlled instance's actual conversations, inspect tool results, continue a chat directly, and handle native approval requests. The controller can run on the same computer as your primary desktop app or on another supported host.

This is access to the controller environment, not merely permission to chat with an agent. Pair only trusted operator devices. Giving someone a Matrix identity or permission to message an agent does not require sharing your pairing code.

## 1. Select the controller on its host

Run these commands on the computer running Hardline. Use the same checkout and compatible Codex executable as the listener:

```sh
export HARDLINE_HOME=/absolute/path/to/hardline
# Optional if the compatible executable is not on PATH:
# export HARDLINE_CODEX_CLI=/absolute/path/to/codex
CODEX_CLI="${HARDLINE_CODEX_CLI:-codex}"
```

The controller's Codex home is `$HARDLINE_HOME/.runtime/codex-home`. Keep this exact `CODEX_HOME` on every controller command. Omitting it may pair your normal desktop instance instead.

If this home has not been authenticated yet, sign in using your ChatGPT account:

```sh
CODEX_HOME="$HARDLINE_HOME/.runtime/codex-home" "$CODEX_CLI" login
```

Use the account and workspace you intend to operate from. A separate Codex home does not create a new subscription or guarantee isolation of account-level connectors and plugins.

## 2. Start remote control and generate a code

```sh
CODEX_HOME="$HARDLINE_HOME/.runtime/codex-home" "$CODEX_CLI" remote-control start --json
CODEX_HOME="$HARDLINE_HOME/.runtime/codex-home" "$CODEX_CLI" remote-control pair --json
```

`start` starts the managed daemon with remote control enabled, or connects to the existing managed daemon. `pair` returns a short-lived code; the documented JSON fields include `manualPairingCode`, `pairingCode`, `environmentId`, and `expiresAt`. Use the manual code in the desktop connection flow and check its expiry. Treat the output as private, and do not commit or publish it.

Generate a fresh code for another device or after expiry by running `pair` again. If pairing times out while the daemon is starting, run `start` again, let startup finish, and retry `pair`. Do not restart busy agents just to obtain a new code.

These commands are experimental Codex functionality and can change between versions. Check `"$CODEX_CLI" remote-control --help` and the [official developer command reference](https://learn.chatgpt.com/docs/developer-commands).

## 3. Pair from your primary desktop app

In the primary Codex/ChatGPT desktop app, open **Settings → Connections → Control other devices**, choose the add/connect action, and enter the manual code. Complete any account/workspace verification shown by the app. Labels and availability vary by desktop version and workspace policy; see [OpenAI's remote connections guide](https://learn.chatgpt.com/docs/remote-connections).

Give the connection a clear name such as **Hardline controller** so you can distinguish it from your everyday desktop environment. The code belongs to the controlled Codex home, even when both instances run on the same physical computer. You do not need to launch a second desktop window to operate through the remote connection.

## 4. Confirm you are looking at controller chats

Open one of the existing controller conversations through the connected host. In the tested desktop UI, remote chats appeared in Recents with a globe icon; do not expect a separate standalone “Tasks” page. Select the correct connected host when the UI offers a host selector.

Compare the conversation ID with the agent's `thread_id` in your private `agents.json`. Send a harmless direct test in that chat and confirm the response comes from the expected agent/folder. Direct chat input starts Codex work regardless of whether Hardline Matrix routing is paused, so keep the test within the agent's charter.

Hardline never approves tools itself. If a turn requires native approval, open that same remote conversation and inspect the request before deciding. Remote capabilities and approvals depend on the host configuration and the platform; a Matrix reply does not automatically answer a Codex approval prompt.

## Troubleshooting

- **Connected, but no conversations:** confirm the code was generated with the controller's exact `CODEX_HOME`; confirm the agent's registered conversation has at least one saved turn. An empty desktop project does not prove that a controller chat exists.
- **“No rollout found”:** pairing cannot recover a chat that never saved its conversation record. Follow the empty-chat initialization guidance in the README; preserve the agent's folder and identity when reconciling its registration.
- **Stale or expired code:** generate a new code with `pair`; do not reuse an old screenshot or saved code.
- **Wrong Codex executable or home:** inspect the selected daemon with `CODEX_HOME="$HARDLINE_HOME/.runtime/codex-home" "$CODEX_CLI" app-server daemon version`. This reports version/socket information, not a guarantee that every remote feature is available.
- **Host unavailable:** check power, network connectivity, authentication, and the managed daemon. Hardline's Matrix task interface also needs its listener running. Pairing a host does not keep it awake automatically.
- **Disconnecting:** manage/revoke the operator device through the host connection settings. `codex remote-control stop` stops the controller daemon and can interrupt agent work; do not use it merely to close the viewing client.
