#!/usr/bin/env python3
"""Dependency-free local HTTP server for Kerdon MSP Mini-ERP Cockpit and API."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kerdon_aws.handlers import dispatch_http_event  # noqa: E402


class KerdonLocalHandler(BaseHTTPRequestHandler):
    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        path_part, _, qs_part = self.path.partition("?")
        event = {
            "requestContext": {"http": {"method": method, "path": path_part}},
            "rawPath": path_part,
            "rawQueryString": qs_part,
            "headers": {k: v for k, v in self.headers.items()},
            "body": raw_body,
        }
        resp = dispatch_http_event(event, role_mode="all")
        status = int(resp.get("statusCode", 200))
        self.send_response(status)
        for hk, hv in (resp.get("headers") or {}).items():
            self.send_header(hk, hv)
        self.end_headers()
        if method != "HEAD":
            body_bytes = str(resp.get("body") or "").encode("utf-8")
            self.wfile.write(body_bytes)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch("OPTIONS")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("127.0.0.1", port), KerdonLocalHandler)
    print(f"Kerdon MSP local cockpit running at http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
