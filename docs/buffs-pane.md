# Buffs Pane

Visualises `state.char.affects` — the active affect list maintained by
`lua/core/affects.lua`. Touch this file when changing the renderer, the
pane position, or the toggle wiring.

**Current state:** placeholder renderer. Affect rendering is pending (buffs
renderer phase). The pane opens, sits correctly in the right column, and
can be toggled, but its content area is blank.

## Architecture

```
lua/core/affects.lua ──► state.char.affects
                                │
                    affects_changed event
                                │
                                ▼
                    bridge/buffs_pane.py  (placeholder — pending renderer phase)
```

## Position

Right column (top to bottom): `status` → `buffs` → `comm` → `ui` → `dev`.

When a subset of right panes is open, ordering is preserved — buffs always
sits directly below status (when status is open) and above comm (when comm
is open). Toggling other right panes in any order does not break the
vertical order.

## Toggle

| Method            | Mechanism                                  |
|-------------------|--------------------------------------------|
| `cp -b`           | `toggle_pane.sh buffs` (runtime only)      |
| BUFFS button      | `toggle_pane.sh buffs --persist`           |

Persistence key: `show_buffs` in `bridge/startup.conf`. Fresh-install
default is `0` (pane closed). Existing installs without the key fall
through to the `${show_buffs:-0}` runtime guard — no change on upgrade.

The BUFFS button in the input-pane menu bar reflects the current pane state
(ON / OFF colour). Button state is polled from `startup.conf` every 250 ms
via mtime comparison — the same path as the other menu buttons.

## Pane title and border

Pane title: `buffs`. The `pane-border-format` in `bridge/tmux_start.sh`
maps this to the label ` Buffs ` when headers are on.

## Data layer

`state.char.affects` and the supporting disk files (`logs/affect_times/`,
`logs/affects_active/`) continue to be maintained by `lua/core/affects.lua`
regardless of whether the buffs pane is open. The data layer is independent
of the visualisation layer.

See [`docs/affects.md`](affects.md) for the full data-layer specification.

---
Back to [architecture.md](../architecture.md).
