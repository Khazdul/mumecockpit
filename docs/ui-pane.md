# UI Pane

A `prompt_toolkit` full-screen application that tails `logs/ui.log` directly,
rendering coloured Lua brain output with anchor-bottom scrollback. Touch this
file when changing the renderer, the scroll model, or the spawn call.

## Architecture

```
lua/brain.lua helpers
  ui(), script_ui(), system_ui(), ui_warn(), ui_err(), affect_ui()
                │
                ▼
        logs/ui.log  (ANSI text, one line per event)
                │
         inode + size poll (250 ms)
                │
                ▼
        bridge/ui_pane.py
        prompt_toolkit Application
        anchor-bottom; wrap-aware scroll; overflow indicator
```

### Source of truth

`logs/ui.log` is written directly by the Lua brain helpers defined in
`lua/brain.lua`. Each helper writes one ANSI-coded line per event. The pane
tails this file without any intermediate state file; no Lua changes are needed
to wire up the pane.

`logs/ui.log` is truncated to zero at session start by `bridge/tmux_start.sh`,
so the pane always shows only the current session's output.

### Startup read

On launch, `ui_pane.py` opens `logs/ui.log`, reads the entire file, takes the
last `MAX_LINES = 1000` lines, and records the byte offset (equal to the file
size at open time) and inode number (`os.fstat().st_ino`).

### Polling

An asyncio task polls every 250 ms via `os.stat()`:

| Condition                               | Action                                             |
|-----------------------------------------|----------------------------------------------------|
| `size > _byte_offset`                   | Read new bytes from `_byte_offset`; append lines   |
| `inode != _file_inode` or `size < _byte_offset` | Rotation/truncation; re-read up to MAX_LINES |
| File does not exist                     | Clear in-memory list; retry next tick              |

On any change, calls `app.invalidate()`.

### Rendering

`bridge/ui_pane.py` is a `prompt_toolkit` full-screen `Application`
(`mouse_support=True`, `full_screen=True`, `color_depth=ColorDepth.DEPTH_24_BIT`).

Each in-memory log line is an ANSI string. Lines are converted to fragments via
`to_formatted_text(ANSI(line))` and joined with `("", "\n")` separators in a
`FormattedTextControl` inside a `Window(wrap_lines=True)`. A `get_vertical_scroll`
callback pins rendered content to the bottom of the window (`_anchor_bottom`,
same as `comm_pane.py`) so the newest line is always at the bottom when live.

ANSI SGR sequences are stripped via `_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")`
for wrap-aware row-count calculations.

## Scroll

`_scroll_offset` is the number of newer lines hidden below the visible window.
`0` means live-follow (sticky bottom); `N > 0` means `N` lines are scrolled
off the bottom.

Mouse-wheel up/down on the list (`ListControl`) increments/decrements
`_scroll_offset`. The visible slice is calculated as:

```
list_height = H - (1 if _scroll_offset > 0 else 0)
anchor_idx  = total - 1 - _scroll_offset
# walk backward from anchor until list_height display rows accumulated
visible     = _lines[start : anchor_idx + 1]
```

**Wrap-aware `max_offset`** — on each scroll-up tick the handler walks forward
from `_lines[0]`, accumulating wrapped display rows via `_row_count`. The
smallest index `i` at which the running sum reaches `list_height` gives
`max_offset = total - 1 - i`. This pins the oldest line at the top of the
window when fully scrolled up, with no blank rows above it.

**Sticky-bottom on new lines:** when `_scroll_offset > 0` and a poll appends
`N` new lines, `_scroll_offset` is increased by `N` so the visible content
does not shift. Lines dropped from the front (oldest) when `MAX_LINES` is
exceeded do not change `_scroll_offset` — it counts from the end.

### Indicator

A 1-row `ConditionalContainer` sits below the list window. It is visible when
`_scroll_offset > 0`.

| Condition          | Text                    | Clickable                      |
|--------------------|-------------------------|--------------------------------|
| `_scroll_offset > 0` | `↓ N newer messages`  | Yes — resets offset to 0 (live)|

The indicator occupies its own `Window` so `wrap_lines=True` on the list can
never push it off the bottom.

## Content

Content is written to `logs/ui.log` by the Lua brain helpers. The pane renders
their ANSI codes verbatim. See [`docs/ui-messaging.md`](ui-messaging.md) for
the full message format spec and colour palette.

Prefixes rendered in the pane:

| Prefix      | Helper        | Colour            |
|-------------|---------------|-------------------|
| `▶ NAME:`   | `script_ui`   | Teal `#26C6DA`    |
| `● SYSTEM:` | `system_ui`   | Blue `#42A5F5`    |
| `◆ TYPE:`   | `affect_ui`   | Type-specific     |
| `⚠ WARN:`   | `ui_warn`     | Amber `#FFB300`   |
| `✖ ERROR:`  | `ui_err`      | Red `#E53935`     |

Dynamic values within messages are rendered in bold yellow (`#FFEE58`) via
`ui_var()`.

## Pane title and border

Pane title: `ui`. The `pane-border-format` in `bridge/tmux_start.sh` maps
this to the label ` UI ` when headers are on.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -u`                           | `toggle_pane.sh ui --persist`                   |
| In-game popup → Options           | `toggle_pane.sh ui --persist`                   |
| Launcher Options → UI pane        | `_save_conf` → `startup.conf show_ui`           |

Persistence key: `show_ui` in `bridge/startup.conf`. Fresh-install default
is `1` (UI pane on).

## Layout integration

### Pane position

Right column (top to bottom): `status` → `buffs` → `comm` → `ui` → `dev`.

### Height

`ui_height` in `bridge/layout.conf`. User-resizable: dragging the ui↔dev
border persists the new value via `on_pane_resize.sh`.

### Width

The right column has no minimum width. `ui_width` from `bridge/layout.conf`
is the sole authority (ADR 0038). `MAIN_MIN = 30` constrains the main pane,
not the right column.

---
Back to [architecture.md](../architecture.md).
