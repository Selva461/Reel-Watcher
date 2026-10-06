"""Tiny progress feed for the Reel Shelf app while the phone setup runs (http://127.0.0.1:8766/)."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = os.path.expanduser("~/.reel-shelf-setup.json")
LOG = os.path.expanduser("~/reel-shelf-setup.log")


def last_line() -> str:
    try:
        with open(LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(text.replace("\r", "\n").splitlines()):
        line = "".join(c for c in line if c.isprintable()).strip()
        if line:
            return line[-140:]
    return ""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        state["detail"] = last_line()
        body = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8766), Handler).serve_forever()
