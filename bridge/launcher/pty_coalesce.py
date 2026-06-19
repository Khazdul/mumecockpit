#!/usr/bin/env python3
"""PTY-coalescing output pump for the cockpit game pane.

tt++ writes one server line per write() to its controlling-terminal stdout,
and because that stdout is a tty each write is flushed immediately. A burst
(e.g. `score` / `eq` in a full room) therefore reaches the tmux pane as many
separate one-line writes, and the terminal/tmux can redraw between them —
producing a visible mid-burst partial frame (flicker).

This pump sits between tt++ and the tmux pane. It spawns tt++ on a fresh pty
(so tt++ still believes it owns a tty and keeps its per-line flushing), then:

  - INPUT  (tmux pane -> tt++): forwarded immediately, byte-for-byte, with no
    buffering or delay. This is the keystroke -> server hot path; it must add
    zero latency.
  - OUTPUT (tt++ -> tmux pane): appended to a buffer and flushed as a single
    write() per batch, optionally bracketed in DEC 2026 synchronized-output
    markers so each batch renders atomically. Batches are bounded by a sub-ms
    read-idle debounce, a size cap, and a max-hold ceiling so output can never
    be held indefinitely under a continuous stream.

The pump never parses, splits, or rewrites the byte content — it only batches
by timing and optionally brackets each batch with the ESC[?2026h / ESC[?2026l
pair.

Invocation:
    pty_coalesce.py -- <command> [args...]

Tunables (env, read once at startup). Defaults are grounded in a measured
~1.7 ms span for a typical ~21-line burst: the debounce closes the batch just
after the burst goes idle, the max-hold/cap failsafes bound worst-case hold.

    MUME_COALESCE_MS      debounce (read-idle) in ms, default 1
    MUME_COALESCE_MAX_MS  max hold from oldest buffered byte, ms, default 12
    MUME_COALESCE_CAP     size cap in bytes, default 32768
    MUME_COALESCE_SYNC    1 = wrap each batch in DEC 2026 markers,
                          0 = write the batch as-is (default)

DEC 2026 wrapping is opt-in: plain write()-batching already renders bursts
atomically on the tested stack (foot 1.16 / tmux 3.4), so the markers add no
benefit there and stay off unless explicitly enabled.

STDLIB only; POSIX only (Linux + macOS) — no epoll-specific code, the event
loop is the portable `selectors` module.
"""

import os
import pty
import tty
import termios
import fcntl
import signal
import selectors
import sys
import time

# DEC 2026 synchronized-output markers (begin / end).
SYNC_BEGIN = b"\x1b[?2026h"
SYNC_END = b"\x1b[?2026l"

READ_CHUNK = 65536

# Signals we forward verbatim to the child. SIGWINCH is handled specially
# (winsize re-copy), so it is not in this set.
FORWARD_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _write_all(fd, data):
    """Write all of `data` to `fd`, looping over partial writes."""
    mv = memoryview(data)
    while mv:
        n = os.write(fd, mv)
        mv = mv[n:]


def _copy_winsize(src_fd, dst_fd):
    """Copy the terminal window size from src_fd to dst_fd.

    The 8-byte TIOCGWINSZ payload is passed straight to TIOCSWINSZ — no need
    to unpack rows/cols. Setting the inner master's winsize makes the kernel
    deliver SIGWINCH to the child, so tt++ re-renders at the new dimensions.
    """
    try:
        ws = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, ws)
    except OSError:
        pass


def main():
    argv = sys.argv[1:]
    if len(argv) < 2 or argv[0] != "--":
        sys.stderr.write("usage: pty_coalesce.py -- <command> [args...]\n")
        return 2
    cmd = argv[1:]

    debounce_s = _env_int("MUME_COALESCE_MS", 1) / 1000.0
    max_hold_s = _env_int("MUME_COALESCE_MAX_MS", 12) / 1000.0
    cap_bytes = _env_int("MUME_COALESCE_CAP", 32768)
    sync = os.environ.get("MUME_COALESCE_SYNC", "0") != "0"

    # Spawn the child on a NEW pty. In the child, stdin/stdout/stderr are the
    # pty slave and it is the controlling terminal; execvp inherits cwd + env.
    pid, master_fd = pty.fork()
    if pid == 0:
        try:
            os.execvp(cmd[0], cmd)
        except OSError:
            os._exit(127)
        os._exit(127)  # not reached

    # Apply the outer winsize to the inner pty before tt++ paints anything.
    _copy_winsize(1, master_fd)

    # Self-pipe for signal delivery: set_wakeup_fd writes the signal number to
    # the pipe, waking the selector promptly. Trivial handlers must be
    # installed so Python treats the signals as caught (default SIGWINCH is
    # ignore, which would never write to the wakeup fd).
    wakeup_r, wakeup_w = os.pipe()
    os.set_blocking(wakeup_r, False)
    os.set_blocking(wakeup_w, False)
    signal.set_wakeup_fd(wakeup_w)
    for sig in (signal.SIGWINCH,) + FORWARD_SIGNALS:
        signal.signal(sig, lambda *_a: None)

    old_termios = None
    exit_code = 0
    try:
        # The outer terminal (our fds 0/1, the tmux pane pty) becomes a
        # transparent byte conduit: raw mode, restored on exit. The inner pty's
        # line discipline is owned by tt++ — we never touch it.
        old_termios = termios.tcgetattr(0)
        tty.setraw(0, termios.TCSANOW)

        sel = selectors.DefaultSelector()
        sel.register(0, selectors.EVENT_READ, "stdin")
        sel.register(master_fd, selectors.EVENT_READ, "master")
        sel.register(wakeup_r, selectors.EVENT_READ, "wakeup")

        buf = bytearray()
        first_byte_at = 0.0  # monotonic time the buffer became non-empty
        last_read_at = 0.0   # monotonic time of the most recent append

        def flush():
            nonlocal buf
            if not buf:
                return
            if sync:
                _write_all(1, SYNC_BEGIN + bytes(buf) + SYNC_END)
            else:
                _write_all(1, bytes(buf))
            buf = bytearray()

        running = True
        while running:
            # Block until an event, or until the buffer's next flush deadline.
            if buf:
                now = time.monotonic()
                deadline = min(last_read_at + debounce_s,
                               first_byte_at + max_hold_s)
                timeout = max(0.0, deadline - now)
            else:
                timeout = None

            for key, _mask in sel.select(timeout):
                tag = key.data

                if tag == "master":
                    # OUTPUT: append, never write immediately.
                    try:
                        data = os.read(master_fd, READ_CHUNK)
                    except OSError:
                        data = b""
                    if not data:
                        # Inner EOF: child exited. Flush the tail and stop.
                        flush()
                        running = False
                        break
                    if not buf:
                        first_byte_at = time.monotonic()
                    buf += data
                    last_read_at = time.monotonic()

                elif tag == "stdin":
                    # INPUT: forward immediately, zero added latency.
                    try:
                        data = os.read(0, READ_CHUNK)
                    except OSError:
                        data = b""
                    if not data:
                        # Outer stdin EOF: the tmux pane is gone. Hang up the
                        # child and stop.
                        try:
                            os.kill(pid, signal.SIGHUP)
                        except ProcessLookupError:
                            pass
                        running = False
                        break
                    _write_all(master_fd, data)

                elif tag == "wakeup":
                    try:
                        signos = os.read(wakeup_r, 4096)
                    except OSError:
                        signos = b""
                    for signo in signos:
                        if signo == signal.SIGWINCH:
                            _copy_winsize(1, master_fd)
                        elif signo in FORWARD_SIGNALS:
                            try:
                                os.kill(pid, signo)
                            except ProcessLookupError:
                                pass

            if not running:
                break

            # Flush when any failsafe or the debounce fires.
            if buf:
                now = time.monotonic()
                if (len(buf) >= cap_bytes
                        or now - first_byte_at >= max_hold_s
                        or now - last_read_at >= debounce_s):
                    flush()

        # Drain anything left, then reap the child and adopt its exit status so
        # pane lifecycle / relog detection behave exactly as before.
        flush()
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = 0
        if os.WIFEXITED(status):
            exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            exit_code = 128 + os.WTERMSIG(status)
        else:
            exit_code = 1
    finally:
        signal.set_wakeup_fd(-1)
        if old_termios is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, old_termios)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
