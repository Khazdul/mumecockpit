#!/usr/bin/env python3
# bridge/buffs_pane.py — placeholder for the buffs pane renderer.
# Renders nothing. Actual affect rendering is pending (buffs renderer phase).

import signal
import sys
import time


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def main():
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    signal.signal(signal.SIGTERM, lambda s, f: (_restore_cursor(), sys.exit(0)))
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
