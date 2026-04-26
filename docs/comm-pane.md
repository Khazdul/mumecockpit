# Communication Pane

The comm pane is a right-column tmux pane positioned between `status` and `ui`
(top to bottom: status → comm → ui → dev). It displays `state.comm.history` with
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
                                             serialises history + channels
                                             to bridge/comm.state (JSON);
                                             reads comm.state at load
                                             to survive cp -r
                                                        │
                                            mtime change │  250 ms poll
                                                        ▼
                                          bridge/comm_pane.py
                                          prompt_toolkit full-screen
                                          Application with mouse_support
                                                        │
                                          reads/writes  │
                                                        ▼
                                          bridge/comm_filters.conf
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

### cp -r persistence

At Lua load time, `comm_state.lua` calls `_load_state_file()`, which reads and
JSON-decodes the previous `bridge/comm.state`. It populates `state.comm.history`
(clamped to `max_size`) and `state.comm.channels` (name + caption only; label
is re-derived). After loading, `serialize()` is called once to write a
well-formed file. This means channel header and history reappear immediately
after `cp -r`, even though `Comm.Channel.List` is not re-emitted on a
persistent TCP connection. Filter state survives `cp -r` independently:
`comm_pane.py` reads `comm_filters.conf` at startup.

### Disconnect policy

`state.comm.history` is **not** cleared on `SESSION DISCONNECTED`. Channel
history is retained across reconnects within the same brain process. `cp -r`
restarts Lua; `_load_state_file()` repopulates from the previous run.
This diverges from `status_pane`, which blanks on disconnect because its
fields have meaningful null states. Communication history is purely
append-only log data with no meaningful null state.

## comm.state schema

JSON, atomic write (tmp + rename), gitignored. Filter state is **not** included
— it is owned by `comm_pane.py` and stored separately in `comm_filters.conf`.
The file also serves as a load-time cache: `comm_state.lua` reads it at startup
to repopulate history and channels after `cp -r`.

```json
{
  "channels": [
    { "name": "tells",    "label": "T", "caption": "Tells" },
    { "name": "narrates", "label": "N", "caption": "Narrates" }
  ],
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

**`history`** — full `state.comm.history`, including ANSI codes verbatim in the
`text` field. dkjson encodes `\x1b` as ``; Python's json module decodes it
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

Filter state lives in `bridge/comm_filters.conf` (gitignored), owned entirely by
`comm_pane.py`. Lua does not read or write this file.

Format: one `name=true|false` line per explicitly-set channel. Missing key means
enabled (sparse-map semantics, default-on for new channels).

`comm_pane.py` loads the file at startup via `_load_filters()`. On every toggle,
`_save_filters()` writes atomically (tmp + rename). No tt++ involvement — toggling
a filter is entirely silent; nothing appears in the game pane.

See [docs/decisions/0010-comm-filter-persistence.md](decisions/0010-comm-filter-persistence.md).

## comm_pane.py

`bridge/comm_pane.py` — prompt_toolkit `Application(full_screen=True,
mouse_support=True)`.

### Layout

`HSplit([header_window, list_window])`. Header height fixed at 1. List fills
remaining rows.

### Header

`FormattedTextControl` with `(style, text, mouse_handler)` tuples. One cell per
channel, 3 columns wide (` label ` — space + letter + space). Background colour
indicates filter state:

| State      | Style                      |
|------------|----------------------------|
| Enabled    | `C_LABEL_ON` — deep green  |
| Disabled   | `C_LABEL_OFF` — dark red   |

Padded cells abut directly — no separator between them. Each cell's mouse
handler calls `forward_toggle(channel.name)` on `MouseEventType.MOUSE_DOWN`.

`forward_toggle(name)` flips `_filters[name]`, calls `_save_filters()`, and
calls `_app.invalidate()`. No subprocess, no tmux, no tt++ involvement.

Using `MOUSE_DOWN` (rather than `MOUSE_UP`) means toggling fires on the press
event. This eliminates missed clicks caused by press and release landing on
different fragments.

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

| Event                         | Effect                                                              |
|-------------------------------|---------------------------------------------------------------------|
| Mouse wheel up on list        | `_scroll_offset += 1` (cap at `max(0, total - (list_height - 1))`) |
| Mouse wheel down on list      | `_scroll_offset -= 1` (floor at 0)                                 |
| New messages while offset > 0 | `_scroll_offset += delta` (sticky view)                            |
| Click `↓ N newer messages`    | `_scroll_offset = 0` (jump to bottom)                              |
| Filter flip                   | `_scroll_offset` clamped against new list length on next render    |

Mouse wheel scroll is handled by `ListControl`, a `FormattedTextControl`
subclass that overrides `mouse_handler`. On `SCROLL_UP`/`SCROLL_DOWN` events
not consumed by the base class, it adjusts `_scroll_offset` and calls
`_app.invalidate()`. The previous `@kb.add("<scroll-up>")` / `<scroll-down>`
key bindings were no-ops and have been removed.

`_scroll_offset` is clamped against `max(0, total - (list_height - 1))` so
the oldest message stays pinned to the top once reached. This prevents blank
rows above the oldest message and the all-blank locked-view state.

When `_scroll_offset > 0`, the last visible row of the list is the indicator:

```
↓ N newer messages
```

in `C_INDICATOR` style (amber, italic — reads as system meta-information, not
chat content). Clicking it (`MOUSE_DOWN`) resets offset to 0.

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
| `C_INDICATOR`     | `fg:#d4a04e italic`                  | ↓ N newer messages       |

## Layout integration

### Pane position

Right column, top to bottom: **status → comm → ui → dev**. The comm pane sits
between `status` and `ui`. `dev` is always bottommost. When any subset of panes
is open, ordering is preserved.

### Height

`comm_height` in `bridge/layout.conf` (default 10). Unlike `status_height`
(fixed in phase 1), `comm_height` is user-resizable: dragging the comm↔ui
border persists the new value to `layout.conf` via `on_pane_resize.sh`.

The status↔comm border drag persists `status_height`. The ui↔dev border
persists `ui_height`.

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
