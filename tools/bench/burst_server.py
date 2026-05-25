#!/usr/bin/env python3
"""tools/bench/burst_server.py — burst-latency bench server.

A standalone dev tool used to measure how long a tt++ cockpit session
takes to ingest a tight stream of inbound server lines. The server
pretends to be a MUD: it accepts a TCP connection, then sits idle until
the client writes a line equal to "benchgo", at which point it emits a
single burst: the line ``BENCH_START``, then N fixture lines, then
``BENCH_END``. All lines are CRLF-terminated.

With ``--delay-ms 0`` (the default) the whole burst is sent in one
``sendall()`` so it arrives as a single TCP segment, exercising the
worst-case "all in one go" path that the cockpit will batch-process.
With a non-zero delay the lines are spaced apart, which is useful for
sanity checks rather than for the headline measurement.

"benchgo" is repeatable on a single connection — the operator can take
many samples without reconnecting. After the client disconnects, the
server loops back to ``accept()``.

Standard library only. Python 3.
"""

from __future__ import annotations

import argparse
import signal
import socket
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Burst-latency bench server for the MUME cockpit.",
    )
    p.add_argument("--port", type=int, default=4243,
                   help="TCP port to listen on (default: 4243)")
    p.add_argument("--fixture", type=Path, required=True,
                   help="Path to fixture file; one server line per file line")
    p.add_argument("--lines", type=int, default=10,
                   help="Lines per burst (default: 10); cycles fixture if shorter")
    p.add_argument("--delay-ms", type=int, default=0,
                   help="Sleep between lines, ms (default: 0 = single sendall)")
    return p.parse_args()


def load_fixture(path: Path, n: int) -> list[str]:
    text = path.read_text(encoding="utf-8")
    raw = [line.rstrip("\r\n") for line in text.splitlines() if line.strip() != ""]
    if not raw:
        raise SystemExit(f"fixture {path} contains no non-empty lines")
    return [raw[i % len(raw)] for i in range(n)]


def send_burst(conn: socket.socket, lines: list[str], delay_ms: int) -> None:
    header = b"BENCH_START\r\n"
    footer = b"BENCH_END\r\n"
    payload = [(line + "\r\n").encode("utf-8") for line in lines]
    if delay_ms <= 0:
        conn.sendall(header + b"".join(payload) + footer)
        return
    step = delay_ms / 1000.0
    conn.sendall(header)
    for chunk in payload:
        time.sleep(step)
        conn.sendall(chunk)
    time.sleep(step)
    conn.sendall(footer)


def serve_one_client(conn: socket.socket, lines: list[str], delay_ms: int) -> None:
    rfile = conn.makefile("rb", buffering=0)
    while True:
        raw = rfile.readline()
        if not raw:
            return
        trigger = raw.decode("utf-8", errors="replace").strip()
        if trigger != "benchgo":
            continue
        send_burst(conn, lines, delay_ms)


def main() -> int:
    args = parse_args()
    lines = load_fixture(args.fixture, args.lines)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)

    print(
        f"burst-server: listening on :{args.port} "
        f"fixture={args.fixture} lines={args.lines} delay_ms={args.delay_ms}",
        file=sys.stderr, flush=True,
    )

    def _shutdown(_sig, _frame):
        try:
            srv.close()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        try:
            conn, addr = srv.accept()
        except OSError:
            return 0
        print(f"burst-server: client connected from {addr}",
              file=sys.stderr, flush=True)
        try:
            serve_one_client(conn, lines, args.delay_ms)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            print("burst-server: client disconnected; awaiting next",
                  file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
