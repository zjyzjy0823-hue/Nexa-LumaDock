# Windows Device Client

The Device Client sends this Windows computer's runtime metrics to Nexa-LumaDock using a dedicated Device Token. Device Token should be treated as a secret. `config.json` contains a secret; do not commit it.

1. Add a device in Nexa-LumaDock and generate its Device Token.
2. Copy `config.example.json` to `config.json`; set `serverUrl` and `deviceToken`.
3. Run `python -m pip install -r requirements.txt`.
4. Run `python main.py`. Press Ctrl+C to stop. Use `python main.py --once` for one heartbeat.

The default interval is 30 seconds. The client collects CPU, memory, system drive disk usage, battery (null on desktops without one), uptime, hostname, Windows version, architecture, CPU name and a local IPv4 address when available. Disk usage is for the Windows system drive only. A rejected token or invalid heartbeat payload stops the client. Network and server errors retry with backoff. The client has no remote control, command execution, process management or file browsing features.

Device Token is a bearer credential and can be intercepted on HTTP networks. Use HTTPS for production and cross-machine deployments. HTTP is allowed for `localhost` and `127.0.0.1` only by default. For trusted LAN development, set `"allowInsecureHttp": true` explicitly in `config.json`; this exposes the token to network eavesdropping.
