#!/usr/bin/env bash
SENTINEL="$HOME/MUME/bridge/runtime/.layout_ready"
# Wait up to 2s for the layout build to signal ready.
for _ in $(seq 1 40); do
    [ -f "$SENTINEL" ] && break
    sleep 0.05
done
rm -f "$SENTINEL"
# Hand off to tt++. By default route its controlling-terminal output through
# the pty-coalescing pump (batches per-line writes so bursts render in one
# frame; input is immediate pass-through). MUME_COALESCE=0 is the escape hatch
# to the proven direct exec for A/B testing.
if [ "${MUME_COALESCE:-1}" = "0" ]; then
    cd "$HOME/MUME" && exec tt++ -G ttpp/main.tin
else
    cd "$HOME/MUME" && exec python3 bridge/launcher/pty_coalesce.py -- tt++ -G ttpp/main.tin
fi
