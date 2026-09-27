# OpenClaw Adapter

This adapter connects one Nexa Agent to an installed OpenClaw CLI. OpenClaw is the first adapter; the Nexa Agent Runtime API is adapter independent.

1. Install and configure OpenClaw so `openclaw agent exec --message-file - --json` works locally. See the [official CLI documentation](https://docs.openclaw.ai/cli/agent).
2. Create an Agent in Nexa and generate its Agent Token. Copy `config.example.json` to `config.json`, enter the server URL and token, and keep the file private.
3. Run `python -m pip install -r requirements.txt` and `python main.py` from this directory.

The adapter sends an idle heartbeat, polls queued tasks, claims one task, sends a running heartbeat and a start log, executes the prompt through OpenClaw, then sends the result or failure. It continues polling after each task. While a task executes, a background heartbeat keeps the Agent online. OpenClaw is invoked with an argument array and the task text on standard input; Nexa never executes task text as a shell command.

The Agent Token is a bearer credential. Store it securely, do not commit `config.json`, and use HTTPS for remote deployments. Remote HTTP requires explicit `allowInsecureHttp: true`. A token only controls its own Agent runtime resources. Regenerating or revoking the token invalidates the old value immediately.

Network requests retry transient errors. A 401 or 422 response stops the adapter for operator attention. OpenClaw command errors and timeouts mark claimed tasks failed. Unexpected process termination during an active run requires operator recovery in this version.
