"""No redirects/proxies; public DNS addresses pinned through TLS handshake."""
import http.client
import ipaddress
import json
import socket
import ssl
import time
import threading
import queue
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 65536


class ActionError(Exception):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def public_ip(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_url(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.fragment or parts.port not in (None, 443) or any(c.isspace() for c in url)):
            raise ValueError("Invalid webhook URL")
        host = parts.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Private webhook destination")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not public_ip(host):
                raise ValueError("Private webhook destination")
        return parts
    except (TypeError, ValueError):
        raise ValueError("Invalid webhook destination") from None


def resolve_public(host, timeout=5):
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)
    threading.Thread(target=resolve, daemon=True).start()
    try:
        rows = result.get(timeout=timeout)
    except queue.Empty:
        raise ActionError("webhook_dns", True) from None
    if rows is None:
        raise ActionError("webhook_dns", True)
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or any(not public_ip(address) for address in addresses):
        raise ActionError("webhook_private_address")
    return addresses[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = raw
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
            self.sock.do_handshake()
        except BaseException:
            raw.close()
            raise


def post(config, execution_id):
    parts = validate_url(config["url"])
    deadline = time.monotonic() + config["timeout"]
    address = resolve_public(parts.hostname, min(5, config["timeout"]))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ActionError("webhook_network", True)
    connection = PinnedHTTPSConnection(parts.hostname, address, remaining)
    def abort():
        sock = connection.sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()
    timer = threading.Timer(remaining, abort)
    timer.daemon = True
    timer.start()
    try:
        connection.request("POST", parts.path or "/" if not parts.query else (parts.path or "/") + "?" + parts.query,
                           json.dumps(config["body"]).encode(),
                           {**config["headers"], "Content-Type": "application/json", "Idempotency-Key": execution_id})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ActionError("webhook_redirect")
        if response.length is not None and response.length > MAX_RESPONSE_BYTES:
            raise ActionError("webhook_response_too_large")
        size = 0
        while True:
            if time.monotonic() >= deadline:
                raise ActionError("webhook_network", True)
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ActionError("webhook_response_too_large")
        if not 200 <= response.status < 300:
            raise ActionError("webhook_http_error", response.status in (429, 502, 503, 504))
        return {"statusCode": response.status}
    except (OSError, http.client.HTTPException):
        raise ActionError("webhook_network", True) from None
    finally:
        timer.cancel()
        connection.close()
