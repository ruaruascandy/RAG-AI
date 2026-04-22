import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from auth import issue_token
from db import find_user_by_raw_query, init_db
from utils import load_template, run_system_command

HOST = "127.0.0.1"
PORT = 8081


class DemoHandler(BaseHTTPRequestHandler):
    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/login":
            username = params.get("user", [""])[0]
            password = params.get("pwd", [""])[0]
            user = find_user_by_raw_query(username, password)  # SQL injection by design
            if user:
                token = issue_token(username)
                self._write_json({"ok": True, "token": token, "user": username})
                return
            self._write_json({"ok": False, "error": "invalid credentials"}, status=401)
            return

        if parsed.path == "/run":
            cmd = params.get("cmd", [""])[0]
            output = run_system_command(cmd)  # command injection by design
            self._write_json({"ok": True, "output": output})
            return

        if parsed.path == "/preview":
            file_name = params.get("file", ["index.html"])[0]
            content = load_template(file_name)  # path traversal by design
            self._write_json({"ok": True, "content": content[:300]})
            return

        if parsed.path == "/calc":
            expr = params.get("expr", ["1+1"])[0]
            value = eval(expr)  # noqa: S307 - intentionally unsafe for testing
            self._write_json({"ok": True, "value": value})
            return

        self._write_json({"ok": True, "message": "vuln demo service is running"})


def bootstrap() -> None:
    os.makedirs(os.path.join(os.path.dirname(__file__), "templates"), exist_ok=True)
    init_db()


if __name__ == "__main__":
    bootstrap()
    server = HTTPServer((HOST, PORT), DemoHandler)
    print(f"Demo server listening on http://{HOST}:{PORT}")
    server.serve_forever()
