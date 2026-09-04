from __future__ import annotations

import base64
import hashlib
import html
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def oauth_state() -> str:
    return secrets.token_urlsafe(32)


def pkce_pair(*, hex_challenge: bool = False) -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = digest.hex() if hex_challenge else base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class LoopbackOAuthReceiver:
    """One-use OAuth callback listener bound only to this computer."""

    def __init__(self, redirect_uri: str | None = None):
        parsed = urlparse(redirect_uri or "http://127.0.0.1:0/callback/")
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Automatic sign-in requires an http://127.0.0.1 or http://localhost callback.")
        self.path = parsed.path or "/callback/"
        self._result: dict[str, str] | None = None
        self._event = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                request = urlparse(self.path)
                if request.path.rstrip("/") != receiver.path.rstrip("/"):
                    self.send_error(404)
                    return
                receiver._result = {
                    key: values[0] for key, values in parse_qs(request.query).items() if values
                }
                receiver._event.set()
                error = receiver._result.get("error")
                title = "Connection was not completed" if error else "Account connected"
                message = html.escape(str(
                    receiver._result.get("error_description") or "You can close this browser tab and return to Creator Intelligence."
                ))
                body = (
                    "<!doctype html><meta charset='utf-8'><title>Creator Intelligence</title>"
                    "<style>body{font:18px system-ui;background:#0c111b;color:#f5f7ff;"
                    "max-width:680px;margin:12vh auto;padding:32px}h1{color:#7cdd74}</style>"
                    f"<h1>{title}</h1><p>{message}</p>"
                ).encode()
                self.send_response(400 if error else 200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer((parsed.hostname, parsed.port or 0), Handler)
        host, port = self.server.server_address[:2]
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        self.redirect_uri = f"http://{display_host}:{port}{self.path}"
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def result(self) -> dict[str, str] | None:
        return dict(self._result) if self._result is not None else None

    def wait(self, timeout: float | None = None) -> dict[str, str] | None:
        self._event.wait(timeout)
        return self.result()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
