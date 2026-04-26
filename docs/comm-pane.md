# Communication Pane

The comm pane is a right-column tmux pane positioned between `ui` and `status`
(top to bottom: ui → comm → status → dev). It displays `state.comm.history` with
a one-row click-to-toggle channel-filter header. Touch this file when changing
the renderer, the state-file schema, filter persistence, scroll semantics, or
the label-collision policy.

## Architecture

```
Comm.Channel.Text ──► lua/core/comm_log.lua ──► state.comm.history
Comm.Channel.List ──► lua/core/comm_log.lua ──► state.comm.channels
                                                        │
                                             lua/core/comm_state.lua
                                             wraps both handlers;
                                             owns state.comm.filters
                                             and state.comm.toggle();
                                             serialises to
                                             bridge/comm.state (JSON)
                                                        │
                                            mtime change │  250 ms poll
                                                        ▼
                                          bridge/comm_pane.py
                                          prompt_toolkit full-screen
                                          Application with mouse_support
```

### Load order

`lua/core/comm_log.lua` registers the original `Comm.Channel.Text` and
`Comm.Channel.List` handlers. `lua/core/comm_state.lua` loads immediately after
(alphabetical: `comm_log` < `comm_state`) and wraps both handlers in the same
wrap-and-call pattern as `status_state.lua`.

### State flow

After either wrapped handler runs, `serialize()` writes `bridge/comm.state`
atomically (tmp + rename). `bridge/comm_pane.py` polls via mtime every 250 ms
and redraws on change. `SIGWINCH` is forwarded via signal handler; the app
calls `invalidate()` to trigger a redraw.

### Disconnect policy

`state.comm.history` is **not** cleared on `SESSION DISCONNECTED`. Channel
history is retained across reconnects within the same brain process. `cp -r`
clears it via Lua restart. This diverges from `status_pane`, which blanks on
disconnect because its fields have meaningful null states (e.g. "character is
dead / logged out"). Communication history is purely append-only log data with
no meaningful null state — blanking it on disconnect would discard information
the player may want to review.

## comm.state schema

JSON, atomic write (tmp + rename), gitignored.

```json
{
  "channels": [
    { "name": "tells",    "label": "T", "caption": "Tells" },
    { "name": "narrates", "label": "N", "caption": "Narrates" }
  ],
  "filters": {
    "narrates": false
  },
  "history": [
    {
      "ts": 1714000000,
      "channel": "narrates",
      "talker": "Aragorn",
      "talker_type": "ally",
      "destination": null,
      "text": "with preserved ANSI codes"
    }
  ]
}
```

**`channels`** — derived from `state.comm.channels` (set by `Comm.Channel.List`)
with a computed `label` field. Deterministic label assignment on each serialize.

**`filters`** — sparse map: missing key means the channel is enabled (default-on
for new channels). Only channels with an explicitly flipped state appear here.

**`history`** — full `state.comm.history`, including ANSI codes verbatim in the
`text` field. dkjson encodes `\x1b` as ``; Python's json module decodes it
back to the ESC byte; prompt_toolkit's `ANSI()` class then converts it to styled
fragments.

## Label-collision policy

The label for a channel is the first uppercase character of `channel.name` that
is not already taken by an earlier channel in the `Comm.Channel.List` order. If
all characters of the name are taken, the label falls back to `?`.

Examples with four channels `tells`, `narrates`, `news`, `emotes`:

| Channel   | Taken before | Chosen label |
|-----------|--------------|--------------|
| tells     | —            | T            |
| narrates  | T            | N            |
| news      | T, N         | E (2nd char) |
| emotes    | T, N, E      | M (2nd char) |

This policy is deterministic by `Comm.Channel.List` order. If the server reorders
channels across sessions the labels may change; players relying on muscle memory
should be aware. The policy is documented here rather than in code so the
trade-off is explicit.

## Filter persistence

Filter state lives in `bridge/comm_filters.conf` (gitignored). Format: one
`name=true|false` line per explicitly-set channel. Missing key means enabled.

`state.comm.toggle(name)` flips the effective value (nil→false, true→false,
false→true) and rewrites the file immediately. `comm_state.lua` reads the file
at load time so filters survive `cp -r`.

New channels advertised by `Comm.Channel.List` that are absent from the conf
file appear enabled by default, because the sparse-map representation treats
missing entries as `true`.

See [docs/decisions/0010-comm-filter-persistence.md](decisions/0010-comm-filter-persistence.md).

## comm_pane.py

`bridge/comm_pane.py` — prompt_toolkit `Application(full_screen=True,
mouse_support=True)`.

### Layout

`HSplit([header_window, list_window])`. Header height fixed at 1. List fills
remaining rows.

### Header

`FormattedTextControl` with `(style, text, mouse_handler)` tuples. One
uppercase-letter cell per channel; background colour indicates filter state:

| State      | Style                      |
|------------|----------------------------|
| Enabled    | `C_LABEL_ON` — deep green  |
| Disabled   | `C_LABEL_OFF` — dark red   |

Single-space separator between label cells (no `|` divider). Each cell's mouse
handler calls `forward_toggle(channel.name)` on `MouseEventType.MOUSE_UP`.

`forward_toggle(name)` runs:
```
tmux send-keys -t mume:cockpit.0 "comm_toggle <name>" Enter
```
which reaches `comm_toggle` in tt++, which calls `state.comm.toggle()` in Lua,
which flips the filter and rewrites `comm.state`. The pane picks up the mtime
change within 250 ms.

### List

Each row: `HH:MM <talker> <verb> <text>`

| Field    | Style                        | Notes                              |
|----------|------------------------------|------------------------------------|
| HH:MM    | `C_TIME` — dim blue-grey     | From `ts` (Unix epoch)             |
| talker   | `C_TALKER_*` — per type      | Coloured by `talker_type`          |
| verb     | `C_VERB` — muted blue-grey   | `caption` lowercased               |
| text     | Passthrough ANSI             | Parsed via `prompt_toolkit.ANSI()` |

`talker_type` colour mapping:

| Type    | Style              | Colour    |
|---------|--------------------|-----------|
| ally    | `C_TALKER_ALLY`    | #90ee90   |
| enemy   | `C_TALKER_ENEMY`   | #ff6b6b   |
| neutral | `C_TALKER_NEUTRAL` | #ffd700   |
| npc     | `C_TALKER_NPC`     | #9e9e9e   |
| (unset) | `C_TALKER_UNSET`   | #bdbdbd   |

### Scroll semantics

`_scroll_offset` integer: **0 = bottom (live-follow)**. Increasing values hide
that many messages at the bottom.

| Event                         | Effect                                           |
|-------------------------------|--------------------------------------------------|
| `<scroll-up>` key             | `_scroll_offset += 1` (cap at history length)    |
| `<scroll-down>` key           | `_scroll_offset -= 1` (floor at 0)               |
| New messages while offset > 0 | `_scroll_offset += delta` (sticky view)          |
| Click `↑ N newer messages`    | `_scroll_offset = 0` (jump to bottom)            |
| Filter flip                   | `_scroll_offset` clamped against new list length |

When `_scroll_offset > 0`, the first visible row of the list is the indicator:

```
↑ N newer messages
```

in `C_INDICATOR` style. Clicking it resets offset to 0.

### Colour palette

All constants are defined at the top of `bridge/comm_pane.py`:

| Constant          | Value (CSS-style for prompt_toolkit) | Role                     |
|-------------------|--------------------------------------|--------------------------|
| `C_LABEL_ON`      | `bg:#1e5c30 fg:#ffffff bold`         | Filter on — deep green   |
| `C_LABEL_OFF`     | `bg:#3d1f1f fg:#666666`              | Filter off — dark red    |
| `C_TIME`          | `fg:#5a6a7a`                         | Timestamp — dim          |
| `C_TALKER_ALLY`   | `fg:#90ee90 bold`                    | Ally talker              |
| `C_TALKER_ENEMY`  | `fg:#ff6b6b bold`                    | Enemy talker             |
| `C_TALKER_NEUTRAL`| `fg:#ffd700`                         | Neutral talker           |
| `C_TALKER_NPC`    | `fg:#9e9e9e`                         | NPC talker               |
| `C_TALKER_UNSET`  | `fg:#bdbdbd`                         | Unknown talker type      |
| `C_VERB`          | `fg:#78909c`                         | Channel verb             |
| `C_INDICATOR`     | `fg:#546e7a`                         | ↑ N newer messages       |
| `C_SEP`           | `fg:#37474f`                         | Space between labels     |

## Layout integration

### Pane position

Right column, top to bottom: **ui → comm → status → dev**. The comm pane sits
between `ui` and `status`. `dev` is always bottommost. When any subset of panes
is open, ordering is preserved.

### Height

`comm_height` in `bridge/layout.conf` (default 10). Unlike `status_height`
(fixed in phase 1), `comm_height` is user-resizable: dragging the comm↔status
border persists the new value to `layout.conf` via `on_pane_resize.sh`.

The ui↔comm border drag persists `ui_height`. The status↔dev border snaps back
(status height is fixed at 12 in phase 1).

### Width floor

The 33-column `RIGHT_MIN` floor in `on_window_resize.sh` and `apply_layout.sh`
is driven by the `status` pane's render width. The comm pane has no fixed column
requirement — it adapts to available width.

## Toggle

| Method         | Mechanism                          |
|----------------|------------------------------------|
| `cp -m`        | `toggle_pane.sh comm` (runtime)    |
| (no popup yet) | —                                  |

Persistence key: `show_comm` in `bridge/startup.conf` (not yet wired to the
launcher startup flow; `cp -m` is runtime-only for now).

---
Back to [architecture.md](../architecture.md).
