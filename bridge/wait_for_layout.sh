#!/usr/bin/env bash
SENTINEL="$HOME/MUME/bridge/.layout_ready"
# Wait up to 2s for the layout build to signal ready.
for _ in $(seq 1 40); do
    [ -f "$SENTINEL" ] && break
    sleep 0.05
done
rm -f "$SENTINEL"
cd "$HOME/MUME" && exec tt++ -G ttpp/main.tin
