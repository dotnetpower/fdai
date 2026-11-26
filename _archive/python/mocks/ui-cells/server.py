#!/usr/bin/env python3
"""Static file server + synthetic SSE endpoint for the UI Cells mock.

Serves files from the current directory and streams
data/discovery-stream.jsonl over /events as Server-Sent Events, using the
per-event `at` field (milliseconds from start) to space them.

Stdlib only. No dependencies.

Usage:
    python3 server.py [--port 8081]
"""

import argparse
import json
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
STREAM_FILE = os.path.join(ROOT, "data", "discovery-stream.jsonl")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".map":  "application/json; charset=utf-8",
    ".txt":  "text/plain; charset=utf-8",
    ".md":   "text/markdown; charset=utf-8",
}


def load_stream():
    events = []
    with open(STREAM_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    events.sort(key=lambda e: e.get("at", 0))
    return events


class Handler(BaseHTTPRequestHandler):
    server_version = "UICellsMock/0.1"

    # Quieter access log
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/events":
            self.handle_events(parse_qs(parsed.query))
            return
        if path in ("/", ""):
            path = "/index.html"
        self.serve_static(path)

    def serve_static(self, path):
        # Prevent directory traversal
        clean = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(ROOT, clean)
        if not full.startswith(ROOT) or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(500, "Read error")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def handle_events(self, qs):
        speed = 1.0
        try:
            speed = max(0.05, float(qs.get("speed", ["1.0"])[0]))
        except ValueError:
            pass
        try:
            events = load_stream()
        except OSError as e:
            self.send_error(500, "Cannot open stream: %s" % e)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            self._write_event("hello", {"count": len(events), "speed": speed})
            start_wall = time.monotonic()
            for ev in events:
                target = (ev.get("at", 0) / 1000.0) / speed
                delay = target - (time.monotonic() - start_wall)
                if delay > 0:
                    time.sleep(delay)
                self._write_event(ev.get("type", "message"), ev.get("payload", {}))
            self._write_event("done", {})
        except (BrokenPipeError, ConnectionResetError):
            return

    def _write_event(self, kind, data):
        payload = json.dumps(data, separators=(",", ":"))
        chunk = ("event: %s\ndata: %s\n\n" % (kind, payload)).encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("UI Cells mock serving http://%s:%d/ (SSE at /events)" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
