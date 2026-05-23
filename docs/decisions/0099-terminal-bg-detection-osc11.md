# ADR 0099 — Terminal-background detection via OSC 11

**Status:** Accepted
**Date:** 2026-05-23

## Context

Several pieces of cockpit chrome bake in a black backdrop:

- the tmux inter-pane separator row (`pane-border-style`), painted by
  `bridge/layout/apply_border_style.sh`;
- the launcher's end-of-reel credits canvas, plus the per-row fade ramp
  in `_credits_brightness_to_hex()`;
- the spotlight info-box outline (`█▀▄▌▐` half-blocks and corner `█`s)
  on the bright cyan fill;
- the profile editor's current-line highlight band in editor mode.

On a black terminal each of these blends into the surrounding canvas
because the baked-in black equals the canvas. On any non-black
terminal — a Solarized scheme, a soft-grey theme, a light theme,
anything with a tint — the same chrome reads as a black stripe / black
glyph stack pasted on top of the user's background. The visual
artefacts are most obvious on the tmux separator (a bright grey line
on dark themes) and the spotlight box's outer edge (a black-and-cyan
frame against a tinted desktop).

The cockpit had no concept of the host terminal background. Every
consumer carried a hardcoded `#000000` constant, and `apply_border_style.sh`
was hardcoded to a grey separator before that — chosen because we had
no way to know what the canvas under it was.

## Decision

Detect the host terminal background once at launcher startup, write
the effective value to `bridge/runtime/layout.conf`, and have every
consumer read that single value. Probe via OSC 11 (`ESC ] 11 ; ? BEL`)
on `/dev/tty` while the launcher still owns the tty in cooked mode,
before prompt_toolkit's `Application` starts.

**Implementation.** `bridge/launcher/launcher.py`:

- `_detect_terminal_bg()` opens `/dev/tty` with `O_RDWR | O_NOCTTY`,
  saves termios, switches to raw, writes the OSC 11 query, reads the
  reply with a bounded ~0.25 s `select` deadline, restores termios
  unconditionally, and parses the reply (`rgb:RRRR/GGGG/BBBB` or the
  8-bit-per-channel `rgb:RR/GG/BB` form) into `#rrggbb`. Returns
  `None` on any failure — missing controlling terminal, timeout,
  unparseable reply.
- `_probe_and_persist_terminal_bg()` runs once in `main()` after
  `_load_conf()` (it depends on the loaded `terminal_bg_fallback`).
  Sets `_terminal_bg = detected or fallback`, pre-computes the
  spotlight info-box outline style (`_spotlight_frame_style`) and the
  editor's focused current-line highlight band
  (`_EDITOR_LINE_HL_BG_FOCUSED`) from the resolved value, and writes
  `terminal_bg=<hex>` into `bridge/runtime/layout.conf` (in-place
  append-or-replace; `build_initial_layout.sh` only seeds missing
  keys, so this write survives layout-conf creation).
- The outcome of each probe is logged to `logs/debug.log` as
  `terminal-bg: detected <hex>` or `terminal-bg: detection failed,
  using fallback <hex>`.

**Configurable fallback.** `terminal_bg_fallback` is a new
`startup.conf` key, validated against `^#[0-9a-fA-F]{6}$`, default
`#000000`. Used only when OSC 11 detection fails. Invalid values
silently fall back to `#000000`.

**Precedence: detected-else-fallback.** Detection wins when it
succeeds. A user who alternates between a detecting terminal and a
non-detecting one stays correct on both: the detecting terminal sees
its own background, the non-detecting one sees the configured fallback.
Fallback-wins precedence would have broken the multi-terminal user
(the fallback would override the actual canvas on every detecting
terminal).

**Consumers.** All read the same single source:

- `bridge/layout/apply_border_style.sh` — single authority for tmux's
  `pane-border-style` and `pane-active-border-style`. Reads
  `terminal_bg` from `layout.conf`, paints both as
  `fg=<terminal_bg> bg=<terminal_bg>` so the separator row blends into
  the host terminal background; hard fallback is `fg=black bg=black`,
  only reached on the launcher-skipped `-d` / `-u` / `--no-menu` paths
  (the normal flow always writes a value). Called from
  `build_initial_layout.sh` after `pane-border-status` is set, and
  from `toggle_pane.sh`'s `headers` branch whenever the divider is
  re-enabled.
- Launcher credits canvas + per-row fade ramp
  (`_credits_brightness_to_hex(b, base_hex)` interpolates between the
  effective terminal background and white; per-row style drops
  `bg:#000000` whenever `_terminal_bg` is known so the terminal
  default shows through).
- Spotlight info-box outline (`palette.spotlight_frame_style(_terminal_bg)`
  paints the `█▀▄▌▐` outer-edge glyphs in `fg:<terminal_bg> bg:#00d7d7`,
  pre-computed once at startup into `_spotlight_frame_style`).
- Profile editor's focused current-line highlight band
  (`_editor_focused_line_hl_bg()` lifts the effective terminal
  background toward white when it is dark and toward black when it is
  light by `_EDITOR_LINE_HL_LIFT = 0.12`; on a black terminal this
  reproduces the legacy `bg:#1f1f1f`).

**Independent chrome change.** `C_BUTTON_INACTIVE` in
`bridge/launcher/palette.py` was simultaneously reduced from
`fg:#bcbcbc bg:#1a1a1a` to `fg:#bcbcbc` — no background fill. Inactive
button cells now fall through to the host terminal background, so the
filled-button widgets read flat against any canvas rather than a stack
of near-black slots on a non-black terminal. Listed here because the
two changes ship together; not load-bearing on OSC 11 detection (the
new value works the same on a black terminal as the old one).

## The ConPTY finding

OSC 11 cannot work under WSL2 + Alacritty. Alacritty itself supports
OSC 11 (it replies promptly when invoked natively on Linux / macOS),
but on Windows the WSL2 install routes the WSL session through
**ConPTY** (the conhost virtual-terminal layer). ConPTY does not relay
the OSC 11 query through to Alacritty. Measured behaviour: 0 bytes
read in the full 2-second probe window, no outer tmux in the loop,
clean tty.

This matters because the Windows installer ships **exactly that
environment** — bundled Alacritty, WSL2 entry point. That is the
canonical end-user environment, and it cannot detect. The configurable
fallback (default `#000000`, matching the bundled Alacritty's black
background) is what the installer base relies on out of the box. OSC
11 is the bonus path for terminals that support it: native Alacritty,
iTerm2, gnome-terminal, kitty, wezterm, modern xterm, and so on.

The fallback default of `#000000` is deliberately chosen to match the
shipped Alacritty background, so the installer base sees correct
chrome (invisible separator, blended credits canvas, blended spotlight
outline) with no user configuration.

## Alternatives considered

**(a) A pre-tmux bash detector (`detect_terminal_bg.sh`).** Built and
retired during this work. Was structured as a small standalone script
called from `bridge/launcher/launcher.sh` before the launcher Python
ran. Rejected because the launcher itself needs the value before
prompt_toolkit takes over (credits canvas and spotlight outline both
render inside the launcher's prompt_toolkit Application), so the
launcher has to do the probe regardless. A second detector would have
been redundant infrastructure with two independent failure modes for
the same query. The launcher owns the tty first; it is the right
detection point.

**(b) Probing `sys.stdin` instead of `/dev/tty`.** A bug. `sys.stdin`
is not always the controlling terminal — pipes, redirects, and the
launcher's own startup flows can leave `sys.stdin` pointing somewhere
else, and the OSC 11 reply never lands. `/dev/tty` always resolves to
the controlling terminal when there is one; when there isn't,
`os.open()` fails cleanly and detection returns `None`. The fix to
probe `/dev/tty` rather than `sys.stdin` was the difference between
"detection works in practice" and "detection silently never works."

**(c) A visible grey-line separator fallback.** The original
`pane-border-style` was a hardcoded grey. Rejected for the post-OSC-11
fallback because the installer base would all see it: WSL2 + Alacritty
can't detect, so 100% of the installer-bundled environment would land
on the grey line. The configurable hex fallback (default black,
matching the bundled background) gives the installer base a clean
canvas, and detecting terminals get the right value automatically.

**(d) Parsing `alacritty.toml` for `[colors.primary] background`.**
Fragile and Alacritty-specific. Wouldn't help users on iTerm2,
gnome-terminal, kitty, or anything else. OSC 11 is the standard query
for this; if a terminal supports it, we use it. If it doesn't, the
configurable fallback covers the bundled environment.

**(e) Fallback-wins precedence.** Would have set `_terminal_bg =
fallback or detected`, i.e. always use the configured fallback when
set. Rejected because it breaks the multi-terminal user: configuring
the fallback for the non-detecting terminal would override the
detected value on the detecting terminal. Detected-else-fallback is
the only precedence that stays correct on both terminals
simultaneously.

## Consequences

- **The cockpit's hardcoded black backdrops are gone from the normal
  flow.** Separator, credits canvas, spotlight outline, and editor
  current-line band all paint relative to the effective terminal
  background. On a black terminal the visible result is identical to
  before; on a tinted or light terminal the chrome blends instead of
  reading as black-on-canvas.
- **One detection point, one stored value.** Every consumer reads the
  same `_terminal_bg` (in-process) or the same `layout.conf:terminal_bg`
  (out-of-process). Adding a fourth or fifth consumer is a one-line
  read, not a new detector.
- **Failure is bounded and logged.** The probe has a hard ~0.25 s
  deadline and an unconditional termios restore. It cannot wedge the
  tty or block startup. Every probe result lands in `logs/debug.log`,
  so misbehaviour is diagnosable from a single tail.
- **The installer base sees correct chrome with zero configuration.**
  WSL2 + Alacritty cannot detect; the fallback default matches the
  bundled background; result is the same as if detection had worked.
- **Users on non-black terminals can override the fallback.** Editing
  `startup.conf:terminal_bg_fallback` to their canvas hex restores
  blended chrome on any non-detecting terminal. Detecting terminals
  ignore the fallback.
- **`apply_border_style.sh` is now the single authority for the tmux
  pane-border style.** `build_initial_layout.sh` and the `headers`
  branch of `toggle_pane.sh` both delegate to it; no other script
  should call `tmux set-option pane-border-style` directly.

## Relation to other ADRs

- Builds on the chrome-grammar ADRs
  [ADR 0085](0085-shared-menu-chrome.md),
  [ADR 0086](0086-panes-grid.md),
  [ADR 0087](0087-menu-row-three-grammar-model.md), and
  [ADR 0088](0088-profile-history-frame-rework.md) — those defined
  the cockpit's button-cell and menu-row grammars; this ADR makes the
  outermost canvas under them theme-aware. The `C_BUTTON_INACTIVE`
  no-fill change ships alongside this ADR and is the first chrome
  token to deliberately fall through to the effective terminal
  background.
- Touches the same `bridge/runtime/layout.conf` introduced for the
  width / height keys in [ADR 0030](0030-right-column-heights-free.md)
  and [ADR 0071](0071-per-pane-desired-heights.md); `terminal_bg`
  joins them as the third class of value the file stores.
- Supersedes nothing.
