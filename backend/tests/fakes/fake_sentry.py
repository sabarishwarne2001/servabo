"""A stand-in for a Sentry (or GlitchTip) ingest endpoint (Final session 1, 4A): it accepts the SDK's envelopes and keeps the events.

    with FakeSentry() as sentry:
        dsn = sentry.dsn            # http://publickey@127.0.0.1:PORT/1
        ...
        sentry.events               # the decoded error events received

Nothing here talks to Sentry. The envelope is `header\\n item-header\\n payload` lines; gzip bodies are inflated.
"""

from __future__ import annotations

import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeSentry:
    def __init__(self, port: int = 0, host: str = "127.0.0.1") -> None:
        self.events: list[dict[str, Any]] = []
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def do_OPTIONS(self) -> None:  # noqa: N802 - the browser SDK's preflight
                self.send_response(204)
                for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*"), ("Access-Control-Allow-Methods", "POST, OPTIONS")):
                    self.send_header(k, v)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                outer.requests.append(self.path)
                lines = raw.split(b"\n")
                index = 1
                while index + 1 < len(lines):
                    try:
                        item_header = json.loads(lines[index])
                        payload = lines[index + 1]
                    except ValueError:
                        break
                    if item_header.get("type") == "event":
                        outer.events.append(json.loads(payload))
                    index += 2
                body = b'{"id":"fake"}'
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread: threading.Thread | None = None

    @property
    def dsn(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://publickeyabc123@{host}:{port}/1"

    def start(self) -> "FakeSentry":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def wait_for(self, count: int = 1, timeout: float = 10.0) -> list[dict[str, Any]]:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline and len(self.events) < count:
            time.sleep(0.05)
        return self.events

    def __enter__(self) -> "FakeSentry":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


if __name__ == "__main__":  # pragma: no cover - the browser tests start it from start-stack.sh
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8792)
    args = parser.parse_args()
    with FakeSentry(args.port) as server:
        print(f"fake Sentry on {server.dsn}", flush=True)
        threading.Event().wait()
