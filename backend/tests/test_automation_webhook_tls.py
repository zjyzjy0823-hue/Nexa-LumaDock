"""Real HTTPS transport using an ephemeral trusted fixture, no external service.

Only DNS/trust/port are injected; production SSRF checks are independently tested.
"""
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import threading
import time
import pytest
from sqlalchemy import select
from app.automation import webhook, engine as runtime
from app.models import AutomationExecution as Execution, AutomationActionReceipt as Receipt, utcnow
from test_automation_engine import network, workflow, queue, step


@pytest.fixture
def tls_sink(tmp_path, monkeypatch):
    openssl = shutil.which("openssl")
    if not openssl and Path("C:/Program Files/Git/usr/bin/openssl.exe").is_file():
        openssl = "C:/Program Files/Git/usr/bin/openssl.exe"
    if not openssl:
        pytest.skip("Ephemeral TLS fixture requires openssl")
    cert, key = tmp_path / "fixture-cert.pem", tmp_path / "fixture-key.pem"
    result = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
        "-out", str(cert), "-days", "1", "-subj", "/CN=hooks.example.test", "-addext", "subjectAltName=DNS:hooks.example.test"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert result.returncode == 0
    received = []
    class Sink(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers.get("Idempotency-Key"), body))
            if self.path == "/slow":
                time.sleep(2)
            status = 302 if self.path == "/redirect" else 200
            data = b'x' * 65537 if self.path == "/large" else b'fixture response never persisted'
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except (OSError, ssl.SSLError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    trust = ssl.create_default_context(cafile=str(cert))
    actual_connection = socket.create_connection
    def pinned(address, *args, **kwargs):
        assert address == ("8.8.8.8", 443)
        return actual_connection(("127.0.0.1", server.server_port), *args, **kwargs)
    monkeypatch.setattr(webhook, "resolve_public", lambda *args: "8.8.8.8")
    monkeypatch.setattr(webhook.ssl, "create_default_context", lambda: trust)
    monkeypatch.setattr(webhook.socket, "create_connection", pinned)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield received
    server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_real_https_action_and_committed_receipt_replay(network, tls_sink):
    factory, ids = network
    wid = workflow(factory, ids, "webhook.post", config={"url": "https://hooks.example.test/hook", "body": {"safe": True}})
    eid = queue(factory, wid)
    with factory() as db:
        assert runtime.claim(db, "webhook-worker") == eid; db.commit()
    def response_lost():
        raise RuntimeError("Committed response lost")
    with pytest.raises(RuntimeError):
        runtime.run_claimed(factory, eid, "webhook-worker", after_action=response_lost)
    with factory() as db:
        db.get(Execution, eid).lease_expires_at = utcnow() - timedelta(seconds=1); db.commit()
    step(factory)
    assert len(tls_sink) == 1 and tls_sink[0][1] == eid
    with factory() as db:
        assert db.get(Execution, eid).status == "succeeded"
        assert db.get(Receipt, eid).result_summary == {"statusCode": 200}


@pytest.mark.parametrize("path,code,retryable", [("/redirect", "webhook_redirect", False), ("/large", "webhook_response_too_large", False), ("/slow", "webhook_network", True)])
def test_real_tls_redirect_oversize_deadline(tls_sink, path, code, retryable):
    before = time.monotonic()
    with pytest.raises(webhook.ActionError) as error:
        webhook.post({"url": "https://hooks.example.test" + path, "headers": {}, "body": {}, "timeout": 1}, "tls-fixture")
    assert error.value.code == code and error.value.retryable == retryable
    assert time.monotonic() - before < 1.8
