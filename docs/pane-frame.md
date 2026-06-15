# Pane Frame

The shared in-pane frame for the five right-column `prompt_toolkit` panes —
status, timers, group, comm, ui. Each pane process draws its own foreground-only
border and header label around its content, coloured from the pane's own colour
and toggleable per pane. The `dev` pane is a raw tail and is **never** framed.

All of this lives in one helper, [`bridge/panes/pane_frame.py`](../bridge/panes/pane_frame.py),
imported by each pane renderer. The corner-glyph support resolution lives in a
separate launcher-side module, [`bridge/launcher/frame_corners.py`](../bridge/launcher/frame_corners.py),
which runs once at startup. The height budget that reserves the frame's two rows
lives in [`bridge/layout/right_column_budget.sh`](../bridge/layout/right_column_budget.sh)
(`rc_frame_extra`) — see [docs/bridge-services.md](bridge-services.md) for the
budget detail. The whole feature is specified in
[ADR 0136](decisions/0136-in-pane-borders.md).

## Why in-pane

Before ADR 0136 the panes were separated and labelled by tmux's own chrome:
`pane-border-status` drew a per-pane header line and the inter-pane
`pane-border-style` row was painted to blend into the terminal background
(ADR 0099). A tmux-drawn header could not follow a pane's own colour or react to
per-pane state, and a separator was a single shared row between two panes, not
something either pane owned. The frame moves both into the pane process, so the
border renders with the same adaptive-width logic as the pane content. tmux
`pane-border-status` is now permanently off.

## Helper API (`pane_frame.py`)

The helper caches its config (no per-call file I/O) and refreshes on mtime change
via `start_poll`.

### `frames_enabled(pane_key=None)`

True when the pane's frame is on. `pane_key` defaults to the **derived key** for
the running pane process (see below). Resolves the border contract:

- `border_<key>=1` → on, `=0` → off;
- when `border_<key>` is absent, fall back to `show_pane_dividers` (the retired
  global key);
- when that is also absent, default **on**.

A `pane_key` that is not one of the five framed keys (`dev`, an unknown entry
point, or the derived `None`) → **off**. This is the same contract restated
independently in `rc_frame_extra` — see [The `border_<key>` contract](#the-border_key-contract).

### Derived pane key

The border state is per-pane (`border_<key>` in `startup.conf`), so each pane
process must know which key it owns. `_derive_pane_key()` derives it from the
running script's filename: `status_pane.py` → `status`. Names that don't end in
`_pane.py`, or whose stem isn't one of the five framed keys, yield `None` — the
border then resolves to off, safe by default. This is why `pane_frame` needs no
per-pane wiring; the convention is the contract.

### `inner_width(full_w)` / `inner_height(full_h)`

Content dimensions: `full_w - 2` / `full_h - 2` when the frame is on (the left +
right edges and the top + bottom rows), else the full size. Both resolve against
this pane's derived key. Pane renderers size their content against these.

### `framed(inner_container, pane_key)`

Wraps `inner_container` in the foreground-only border and returns the composed
container. Structure:

- top row — a `Window` whose `FormattedTextControl` builds
  `<TL>▀▀ <label> ▀…▀<TR>` to exactly the terminal width; the header label is
  left-aligned and lives on the border, not in content;
- a `VSplit` of left edge `▌`, `inner_container`, right edge `▐`;
- bottom row — `<BL>▄…▄<BR>`.

Every border `Window` is a `ConditionalContainer` filtered on
`frames_enabled(pane_key)`, so when the frame is off all borders collapse and the
layout reduces to `inner_container` at full size. The glyphs are foreground-only
(half-blocks `▀▄▌▐` plus the resolved corners) so the tmux pane background
(`select-pane -P bg=`) shows through everywhere. The top/bottom text is rebuilt at
render time (it reads `corners()` each draw), so a live corner-style change picked
up by `start_poll` re-renders without a relaunch.

### `border_color(pane_key)`

The hex colour (`#rrggbb`) used for the border line and header label. Shared by
`border_style` but **exposed publicly** (not just internal) so a pane can tint
in-content elements — e.g. gauge labels — to match its frame title. Resolution is
the same as `border_style` below, minus the `fg:` prefix. Cached.

### `border_style(pane_key)`

The `prompt_toolkit` style string (`fg:#rrggbb`) for the border, derived from the
pane's colour (`pane_color_<key>` in `startup.conf`):

- a named pane colour maps through `PANE_BORDER_COLORS` — the pane fill lifted a
  shade or two (`lighten()`, +0x14 per channel) so the frame reads against the
  fill;
- the **terminal-default** pane (`black` / no `bg` override) has no fill to lift,
  so its border is derived from the live terminal background (`layout.conf`
  `terminal_bg`, the same source `apply_border_style.sh` uses — ADR 0099) lifted
  +0x14. On a black terminal this yields `#141414` (visibly darker than the grey
  pane's `#2a2a2a`); on a tinted terminal it tracks that canvas.

`PANE_BORDER_COLORS` and the label map are **restated** in `pane_frame.py`, not
imported from `bridge/launcher/palette.py`: `bridge/panes` must not import
`bridge/launcher` (ADR 0126). Keep `PANE_BORDER_COLORS` mirrored with
`palette.PANE_COLORS`.

### `pane_shades(pane_key, term_bg=None)`

A seven-key shade ramp for a pane, used by content renderers (the status pane's
gauges, bars, and toggle boxes — ADR 0138) to draw in-pane elements that track the
pane's own colour family. The ramp is **a single hue** — the pane colour's `(h, s)`
— walked **down an HSL lightness ramp**; only lightness (and a small per-key
saturation trim) varies, so every shade reads as the same colour at a different
depth. Returns a dict keyed by role:

| Shade    | L  | Role                                                                            |
|----------|----|--------------------------------------------------------------------------------|
| `track`  | 15 | bar background / XP baseline bg / toggle off-box bg                             |
| `dim`    | 27 | XP session-gain bg / TP-baseline fg / gauge labels                             |
| `mid`    | 42 | TP session-gain fg                                                              |
| `paneBg` | 8  | near-bg dark text / tick bg / toggle-box label (on and off)                     |
| `vtext`  | 72 | gauge value text                                                                |
| `label`  | 60 | level badge (name row) / player name                                           |
| `glow`   | 64 | active highlight: active step-tick, wimpy caret, toggle on-box bg              |

(The shade → role mapping lives in the `pane_shades` docstring; the status pane's
own table in [docs/status-pane.md](status-pane.md) restates it with the same `L`
values.)

#### `(h, s)` source

The hue/saturation come from `PANE_SHADE_HS`, **restated** in `pane_frame.py`
rather than imported from `bridge/launcher` (ADR 0126) — the same discipline as
`PANE_BORDER_COLORS` — and mirrored with the palette's pane colours so the ramp
sits in the same colour family as the pane bg/border (ADR 0086). `pane_shades`
walks that one `(h, s)` down the lightness ramp.

For the **terminal-default** (`black` / `None`) pane — and any unknown colour —
there is no palette entry, so `(h, s)` are taken from `term_bg` (the live terminal
background, ADR 0099) via `_hex_to_hs`, and the ramp tracks a tinted terminal. A
neutral / black background has saturation ≈ 0, so the ramp **collapses to greys**
— the same neutral result as the chromatic-free case, including the ConPTY black
fallback; a missing or garbled `term_bg` falls back to neutral too. `term_bg`
defaults to the live terminal background. Cached pane-colour lookup; no file I/O.

`_hsl_to_hex(h, s, l)` does the HSL → `#rrggbb` conversion the ramp is built from;
`_hex_to_hs(hex)` is its partial inverse — it recovers `(hue, saturation)` from a
`#rrggbb` literal (lightness discarded, since the ramp supplies its own) and
returns `(0, 0)` for a non-`#rrggbb` value so a garbled bg collapses to neutral.

### `corners()`

Returns the resolved corner glyph set `(TL, TR, BL, BR)` — the quadrant glyphs
`▛▜▙▟` when `frame_corners_resolved=quadrant` in `layout.conf`, else the full
block `█` at all four corners. Read live at render time so a corner-style change
re-renders without a relaunch.

### `start_poll(app, interval=0.25)`

Spawns an asyncio task that re-reads `startup.conf` and `layout.conf` on mtime
change and calls `app.invalidate()` when anything border-relevant changes:
`startup.conf` for `frames_enabled` / pane colours, `layout.conf` for the resolved
corner glyphs (`frame_corners_resolved`). The corner watch is what lets a live
corner-style change (popup → Panes → Corner style) re-render the corners without a
relaunch. `terminal_bg` is set once at startup, so it is read once at import — not
polled.

### Header labels

| Pane key | Label       |
|----------|-------------|
| `status` | `Character` |
| `timers` | `Timers`    |
| `group`  | `Group`     |
| `comm`   | `Comm`      |
| `ui`     | `UI`        |

## The `border_<key>` contract

The per-pane border-resolution contract is stated in two places — the renderer
(`pane_frame.frames_enabled`) and the height budget (`rc_frame_extra` in
`right_column_budget.sh`). Both must agree; both are restated independently
because `bridge/panes` must not import `bridge/launcher` and the budget is bash
(ADR 0126):

1. `border_<key>=1` → on, `=0` → off;
2. `border_<key>` absent → fall back to `show_pane_dividers` (retired global key);
3. that absent too → default **on**.

The Panes grid (ADR 0086) exposes this as one trailing **Border** column — a
per-pane `[X]`/`[ ]` checkbox writing `border_<key>` — in both the launcher and
the in-game popup. The `dev` row, never framed, renders a dim inert blank there.
`show_pane_dividers` is never written by the menu any more; it is a read-only
fallback.

## Frame-corner resolution (`frame_corners.py`)

Whether the active terminal font renders the four quadrant codepoints
`▛▜▙▟` (U+259B, U+259C, U+2599, U+259F) is resolved **once at startup** and
persisted, mirroring the OSC-11 `terminal_bg` lifecycle (ADR 0099). The corners
must come from the **same font** as the half-block edges `▀▄▌▐` to tile
seamlessly, so the resolver checks coverage of the font family's own file, not a
fallback font that merely carries the glyphs.

- **Setting → resolved.** `frame_corners` in `startup.conf` (`auto` / `quadrant` /
  `block`) resolves to `frame_corners_resolved` (`quadrant` | `block`) in
  `layout.conf`. `quadrant` / `block` force the outcome with no font check;
  anything else (including `None` / invalid) is treated as `auto`.
- **`auto` chain.** Read the active font family from the terminal config named by
  `MUME_TERMINAL` (foot / kitty / alacritty; `foot-managed` counts as foot —
  ADR 0104). An unknown terminal or missing family → `block`. Then check
  coverage: **fontconfig** (`fc-list :family=…:charset=…`, matching the family's
  own name) where `fc-list` is present, else **fontTools** loading the family's
  own font file and checking its cmap. fontTools is imported lazily and guarded,
  so a missing dependency degrades to `block`, never crashes startup. Undetermined
  (no backend, no matching file, read error) → `block`.
- **Persistence.** `resolve_and_persist(setting, layout_path)` writes
  `frame_corners_resolved` into `layout.conf` in place (append-or-replace, never
  raises). It is called by the launcher startup path and by the popup's live
  corner-style change; `pane_frame.corners()` then picks the new value up on its
  poll.

The resolver has no `prompt_toolkit` import and no global state — subprocess and
file reads only, the same discipline as `foot_config.py`.

## Cross-references

- [ADR 0136](decisions/0136-in-pane-borders.md) — the in-pane borders decision:
  frame shape, border colour, corner resolution, per-pane key, menu surface,
  budget.
- [ADR 0099](decisions/0099-terminal-bg-detection-osc11.md) — `terminal_bg`
  source for the terminal-default border, and the persistence lifecycle mirrored
  by `frame_corners_resolved`.
- [ADR 0126](decisions/0126-timers-layout-menu.md) — `bridge/panes` must not
  import `bridge/launcher`; the restated colour/label tables, `PANE_SHADE_HS`, and
  the twice-stated border contract follow that rule.
- [ADR 0086](decisions/0086-panes-grid.md) — the palette pane colours
  `pane_shades` mirrors its `(h, s)` against, and the Panes grid that sets them.
- [ADR 0138](decisions/0138-status-stepped-gauges.md) — the status pane's
  palette-derived stepped gauges, the main consumer of the `pane_shades` ramp.
- [docs/bridge-services.md](bridge-services.md) — the right-column height budget,
  including `rc_frame_extra`'s two-row reservation.
- Per-pane renderers: [docs/status-pane.md](status-pane.md) — the shade → role
  table and the gauge/bar/toggle elements drawn from `pane_shades`;
  [docs/timers-pane.md](timers-pane.md), [docs/group-pane.md](group-pane.md),
  [docs/comm-pane.md](comm-pane.md), [docs/ui-pane.md](ui-pane.md).

---
Back to [architecture.md](../architecture.md).
