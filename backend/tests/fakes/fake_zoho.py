"""A stand-in for Zoho (Final session 1, 3C): the accounts server (consent screen, token, revoke) and the Books API (organizations,
bills), in the shapes Zoho documents. Nothing here talks to Zoho.

    python -m tests.fakes.fake_zoho --port 8791            # for the browser tests (start-stack.sh)
    with FakeZoho() as zoho: ...                            # in a test; `zoho.url` is both the accounts and the API address

The consent screen approves at once and sends the browser back to the redirect URI with a code and the state, the way Zoho does after
the customer clicks Accept. Like Zoho, a refresh token that was revoked is answered with HTTP 200 and {"error": "invalid_code"}.
`POST /__control/revoke` makes every saved sign-in stop working (what happens when a customer removes the app in Zoho, or a token
expires); `POST /__control/organizations` sets the organizations the login can reach.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

DEFAULT_ORGANIZATIONS = [
    {"organization_id": "60001000001", "name": "Meridian Wholesale Pvt Ltd", "country_code": "IN", "is_default_org": True},
    {"organization_id": "60001000002", "name": "Meridian Retail LLP", "country_code": "IN", "is_default_org": False},
]


class FakeZoho:
    def __init__(self, port: int = 0, host: str = "127.0.0.1") -> None:
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, bool] = {}      # token -> valid
        self.access_tokens: dict[str, float] = {}
        self.organizations: list[dict[str, Any]] = [dict(o) for o in DEFAULT_ORGANIZATIONS]
        self.requests: list[tuple[str, str]] = []
        self.token_forms: list[dict[str, str]] = []
        self.revoked: list[str] = []
        self.bills: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # noqa: D401 - silence
                return

            def _send(self, status: int, body: Any = None, headers: Optional[dict[str, str]] = None) -> None:
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _form(self) -> dict[str, str]:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                return {k: v[0] for k, v in parse_qs(raw).items()}

            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                outer.requests.append(("GET", parts.path))
                if parts.path == "/oauth/v2/auth":
                    code = "code_" + secrets.token_hex(8)
                    outer.codes[code] = {"scope": query.get("scope"), "client_id": query.get("client_id"),
                                         "redirect_uri": query.get("redirect_uri"), "access_type": query.get("access_type")}
                    target = f"{query['redirect_uri']}?code={code}&state={query['state']}&location=in&accounts-server=https%3A%2F%2Faccounts.zoho.in"
                    return self._send(302, headers={"Location": target})
                if parts.path == "/books/v3/organizations":
                    token = (self.headers.get("Authorization") or "").replace("Zoho-oauthtoken ", "")
                    if token not in outer.access_tokens or outer.access_tokens[token] < time.time():
                        return self._send(401, {"code": 57, "message": "You are not authorized to perform this operation"})
                    return self._send(200, {"code": 0, "message": "success", "organizations": outer.organizations})
                self._send(404, {"code": 5, "message": "Invalid URL"})

            def do_POST(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                outer.requests.append(("POST", parts.path))
                if parts.path == "/oauth/v2/token":
                    form = self._form()
                    outer.token_forms.append(form)
                    if form.get("grant_type") == "authorization_code":
                        if form.get("code") not in outer.codes or not form.get("client_secret"):
                            return self._send(200, {"error": "invalid_code"})
                        outer.codes.pop(form["code"])
                        refresh = "1000.refresh." + secrets.token_hex(12)
                        outer.refresh_tokens[refresh] = True
                        access = outer._access()
                        return self._send(200, {"access_token": access, "refresh_token": refresh, "api_domain": "https://www.zohoapis.in",
                                                "token_type": "Bearer", "expires_in": 3600})
                    if form.get("grant_type") == "refresh_token":
                        if not outer.refresh_tokens.get(form.get("refresh_token", ""), False):
                            return self._send(200, {"error": "invalid_code"})
                        return self._send(200, {"access_token": outer._access(), "api_domain": "https://www.zohoapis.in",
                                                "token_type": "Bearer", "expires_in": 3600})
                    return self._send(200, {"error": "invalid_request"})
                if parts.path == "/oauth/v2/token/revoke":
                    token = query.get("token", "")
                    if token in outer.refresh_tokens:
                        outer.refresh_tokens[token] = False
                        outer.revoked.append(token)
                    return self._send(200, {"status": "success"})
                if parts.path == "/books/v3/bills":
                    body = json.loads(self._form_raw() or "{}")
                    outer.bills.append(body)
                    return self._send(201, {"code": 0, "message": "The bill has been created.",
                                            "bill": {"bill_id": "bill_" + secrets.token_hex(4), **body}})
                if parts.path == "/__control/revoke":
                    for token in outer.refresh_tokens:
                        outer.refresh_tokens[token] = False
                    return self._send(200, {"revoked": len(outer.refresh_tokens)})
                if parts.path == "/__control/organizations":
                    length = int(self.headers.get("Content-Length") or 0)
                    outer.organizations = json.loads(self.rfile.read(length) or b"[]")
                    return self._send(200, {"organizations": len(outer.organizations)})
                self._send(404, {"code": 5, "message": "Invalid URL"})

            def _form_raw(self) -> str:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length).decode() if length else ""

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread: Optional[threading.Thread] = None

    def _access(self) -> str:
        token = "1000.access." + secrets.token_hex(12)
        self.access_tokens[token] = time.time() + 3600
        return token

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "FakeZoho":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "FakeZoho":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


if __name__ == "__main__":  # pragma: no cover - the browser tests start it from start-stack.sh
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    with FakeZoho(args.port) as server:
        print(f"fake Zoho on {server.url}", flush=True)
        threading.Event().wait()
