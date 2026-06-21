# UI Pane

A `prompt_toolkit` full-screen application that tails `logs/ui.log` directly,
rendering coloured Lua brain output with anchor-bottom scrollback. Touch this
file when changing the renderer, the scroll model, or the spawn call.

## Architecture

```
lua/brain.lua helpers
  ui(), script_ui(), system_ui(), ui_warn(), ui_err(), char_ui()
                │
                ▼
        logs/ui.log  (ANSI text, one line per event)
                │
         inode + size poll (250 ms)
                │
                ▼
        bridge/panes/ui_pane.py
        prompt_toolkit Application
        anchor-bottom; wrap-aware scroll; overflow indicator
```

### Source of truth

`logs/ui.log` is written directly by the Lua brain helpers defined in
`lua/brain.lua`. Each helper writes one ANSI-coded line per event. The pane
tails this file without any intermediate state file; no Lua changes are needed
to wire up the pane.

`logs/ui.log` is truncated to zero at session start by `bridge/launcher/tmux_start.sh`,
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

`bridge/panes/ui_pane.py` is a `prompt_toolkit` full-screen `Application`
(`mouse_support=True`, `full_screen=True`, `color_depth=ColorDepth.DEPTH_24_BIT`).

Each in-memory log line is an ANSI string. Lines are converted to fragments via
`to_formatted_text(ANSI(line))` and joined with `("", "\n")` separators in a
`FormattedTextControl` inside a `Window(wrap_lines=True)`. A `get_vertical_scroll`
callback pins rendered content to the bottom of the window (`_anchor_bottom`,
same as `comm_pane.py`) so the newest line is always at the bottom when live.

ANSI SGR sequences are stripped via `_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")`
for wrap-aware row-count calculations.

### Light-background recolour

The colours are baked into `logs/ui.log` by the Lua emitters for a dark
terminal (bright-white base text, chromatic prefixes). On a light ("paper")
terminal those wash out, so `_recolor(line)` rewrites a line's SGR colours at
render time — operating on a copy, never mutating `_lines`, and never touching
`logs/ui.log` or the emitters. It is applied at the single render choke point in
`_list_text`: `ANSI(_recolor(line))`. `_row_count` keeps using the raw line — a
colour swap doesn't change visible length, so wrap math is unaffected.

`_LIGHT = pane_frame.is_light_bg()` is resolved **once at module load** (the bg
is static). When false, `_recolor` is a no-op and the pane is byte-for-byte
unchanged. When true:

- every truecolor **foreground** (`38;2;R;G;B`) is pulled darker/more-saturated
  through `pane_frame.light_shift` (catching every chromatic prefix and the
  bold-yellow `ui_var` value — its leading `1;` sits outside the match and is
  preserved; already-dark amber/red just deepen slightly);
- the achromatic bright-white base text (`\x1b[1;97m`, which `light_shift` can't
  help) is then literal-replaced with bold dark ink — `pane_frame.dark_ink()`,
  a very dark colour **tinted toward the terminal background** (so on "paper" it
  reads as a dark warm ink that blends, not a flat near-black; on a neutral
  terminal a near-black grey), resolved once at module load (`_DARK_INK`) and the
  leading `1;` kept for bold — run after the truecolor pass so the only remaining
  `97` is this one;
- backgrounds (`48;2;…`), resets (`0m`), and attr-only params are left untouched.

See [docs/pane-frame.md](pane-frame.md) for `light_shift` / `is_light_bg`.

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
| `◆ TYPE:`   | `char_ui`     | Type-specific     |
| `⚠ WARN:`   | `ui_warn`     | Amber `#FFB300`   |
| `✖ ERROR:`  | `ui_err`      | Red `#E53935`     |

Dynamic values within messages are rendered in bold yellow (`#FFEE58`) via
`ui_var()`.

## Pane frame

Pane title: `ui`. The pane carries an in-pane frame (a header row plus a
half-block border) drawn by `pane_frame`, replacing the old tmux
`pane-border-status` header. Content renders within `inner_width` /
`inner_height` (`W-2` / `H-2` when the border is on, full size when off); the
header label is `UI`; the border is per-pane, toggled by `border_ui` in
`startup.conf`. See [docs/pane-frame.md](pane-frame.md) for the frame shape,
border colour, and the `border_<key>` contract.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -u`                           | `toggle_pane.sh ui --persist`                   |
| In-game popup → Options           | `toggle_pane.sh ui --persist`                   |
| Launcher Options → UI pane        | `_save_conf` → `startup.conf show_ui`           |

Persistence key: `show_ui` in `bridge/runtime/startup.conf`. Fresh-install default
is `1` (UI pane on).

## Layout integration

### Pane position

Right column (top to bottom): `status` → `timers` → `comm` → `ui` → `dev`.

### Height

`desired_ui` in `bridge/runtime/layout.conf` (default 5; content rows,
excludes title row). Cold start and WINCH size the pane from this value via
the per-pane allocation algorithm in
[ADR 0071](decisions/0071-per-pane-desired-heights.md). As the
highest-priority survivor (PRIORITY_ORDER head), the ui pane absorbs the
residual rows when the desired-sum doesn't fill the available budget exactly.
Mid-session drag adjusts the height freely and the new value persists as the
next `desired_ui` via `on_pane_resize.sh`. `cp -reset-heights` restores the
shipped default.

### Width

The right column has no minimum width. `ui_width` from `bridge/runtime/layout.conf`
is the sole authority (ADR 0038). `MAIN_MIN = 30` constrains the main pane,
not the right column.

---
Back to [architecture.md](../architecture.md).
