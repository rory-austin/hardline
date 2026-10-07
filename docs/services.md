# Running as a service

Keep the controller in its own checkout and virtual environment. Set `HARDLINE_HOME` to the absolute checkout path and, if needed, `HARDLINE_CODEX_CLI` to the compatible CLI executable. Run `<checkout>/.venv/bin/hardline run` from that checkout.

On macOS, create your own LaunchAgent under `~/Library/LaunchAgents/` with that command, `WorkingDirectory`, the environment variables above, `RunAtLoad=true`, `KeepAlive=true`, and private stdout/stderr paths under `.runtime/`. Load it with `launchctl bootstrap gui/$(id -u) /absolute/path/to/service.plist`. Stop future routing with `launchctl bootout gui/$(id -u)/YOUR_LABEL`. Do not copy a different operator's installed plist.

On Linux, use an equivalent user systemd service. Linux tests exercise the Python code; managed-daemon deployment and filesystem permissions require verification with your installed Codex build. Windows is not supported because the controller uses Unix sockets and flock.

A singleton lock prevents two listeners from running against one controller root. Pausing individual agents allows current turns to finish; stopping the listener does not delete accounts, conversations, or the controlled Codex home. Keep a human-accessible controller client available for approvals.
