#!/usr/bin/env python3
"""Dev-only stand-in for the workstream-D `uh-backend` sidecar.

NOT shipped. CI replaces this with the PyInstaller binary renamed to
`uh-backend-<target-triple>[.exe]`. This stub only implements the readiness
contract so the Tauri shell can be exercised locally without the full backend.
"""
import http.server
import socket
import sys


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<h1>uh-backend dev stub</h1>" if self.path != "/health" else b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # silence
        pass


def main():
    port = free_port()
    print(f"UH_BACKEND_LISTENING {port}", flush=True)
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
