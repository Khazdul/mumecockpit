# Launcher

Pre-tmux startup menu, rendering conventions, and the exec-chain that starts
or returns to the cockpit. Touch this file when changing launcher pages,
rendering behaviour, the startup command-line options, or the return-to-menu
flow.

## Startup

```bash
./start.sh            # show retro startup menu (default)
./start.sh --no-menu  # skip menu, use current bridge/runtime/startup.conf
./start.sh -d         # skip menu, force dev pane on for this run (not persisted)
./start.sh -u         # skip menu, force UI pane on for this run (not persisted)
```

`start.sh` is a thin wrapper that installs dependencies and then:
- Without bypass flags → `exec bash bridge/launcher/launcher.sh` (startup menu)
- With `--no-menu` / `-d` / `-u` → `exec bash bridge/launcher/tmux_start.sh` (direct start)

The return-to-menu path (in-game popup "Exit to main menu") is handled by an
exec-chain inside `tmux_start.sh`: after `tmux attach` returns, the script
checks for `bridge/runtime/.return_to_menu` (written by `ingame_menu.sh` just before
firing `cp -e`) and, if present, `exec`s back into `bridge/launcher/launcher.sh`.
No intermediate bash frame — no flash. `tmux_start.sh` also clears any stale
sentinel at the top of each run so a crash cannot mis-route a subsequent cold
start.

## Startup menu (`bridge/launcher/launcher.py`)

A `prompt_toolkit` full-screen `Application` rendered in the terminal before
tmux launches. `bridge/launcher/launcher.sh` is a thin wrapper that `exec`s
the Python entry; every call site (start.sh, the return-to-menu chain in
`tmux_start.sh`, the Windows shortcut, the update flow's restart path) goes
through that wrapper unchanged.

The UI is a frame stack: a single `DynamicContainer` swaps between `main`,
`profile`, `profile_create_name`, `profile_create_choose`,
`profile_create_copy_picker`, `profile_delete_confirm`, `options`,
`scripts`, `about`, `update_running`, `update_result`, and `exit_confirm`
containers, pushed and popped via `_push_frame` / `_pop_frame`. Each frame
owns its own `KeyBindings` filter (`_in_frame(name)`) so navigation, scroll,
and ESC behave per-frame. The popup architecture (ADR 0062) is the
reference; see `bridge/launcher/ingame_menu.py` for the same patterns.

| Feature | Detail |
|---------|--------|
| Session detect | `tmux has-session -t mume` + `list-clients` re-probed on every render → top item is "Enter game", "Resume game", or "Mirror game (attached elsewhere)" |
| Profile page | Lists `ttpp/profiles/*.tin`; select, create (blank / copy from existing), delete. `default` cannot be deleted. "Create blank" copies from `bridge/launcher/templates/blank_profile.tin` (single source of truth — see ADR 0042). Selected profile is written to `startup.conf` and consumed by `ttpp/core/config.tin` at tt++ startup. |
| Options page | Toggle Character pane / Buffs pane / Group pane / Comm pane / UI / Dev panes; Pane headers; connection mode. Flat minimalist list — no boxed layout-mockup, no progressive hide. Fresh-install defaults: status, buffs, group, comm, ui on; dev off; pane headers on |
| Scripts page | Reads `bridge/runtime/scripts.cache`; scrollable via UP/DOWN, PageUp/PageDown |
| About page | Reads `bridge/launcher/about.txt`; word-wrapped, cached per resize, scrollable. Current version on the right of the title; an "Update available: vX.Y.Z" line appears in `C_ACCENT` when `version.cache` contains a newer tag |
| Update flow | Selecting "Update" runs `bridge/release/update.sh` in a worker thread; result keyed off update.sh's exit codes (0/10/20/21/22/other → complete/no-update/aborted/failed). rc==0 re-execs `bridge/launcher/launcher.sh` to pick up the new code |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/runtime/startup.conf` on Back / ESC; profile selection saved immediately on Enter |

## Rendering conventions

All frames render through `prompt_toolkit` controls. Layout building blocks:

- **Frame stack** — single `DynamicContainer` whose getter routes
  `_current_frame` to one of the prebuilt container trees. Each frame's
  primary `Window` is stored at module level and focused on push so
  keyboard handlers fire reliably.
- **Centered frames** — `main`, `profile`, `options`, the profile-create
  sub-frames, `exit_confirm`, `update_running`, and `update_result` are
  wrapped in `HSplit([window], align=VerticalAlign.CENTER)` so they stay
  visually centred at any terminal height above the minimum.
- **Scrolling frames** — `scripts` and `about` use a three-row split
  (`title` fixed height, `content` `Dimension(weight=1)`, `footer` fixed
  height) with the content control slicing by a scroll offset.
- **Minimum-size gate** — when `cols < 60` or `rows < 18`, the root getter
  returns a single "Terminal too small" container instead of the active
  frame. A `<any>`-filter binding swallows key input while the gate is
  on; Ctrl-C / Ctrl-Q still exit. Resizing past the threshold restores
  the normal UI transparently because the gate is checked on every
  render.
- **Mouse hover / click** — every selectable row carries a per-fragment
  `mouse_handler`. `MOUSE_DOWN` selects-and-activates in a single click.
  `MOUSE_MOVE` updates a hover index that paints the row in `C_HOVER`
  (between `C_ITEM` and `C_ACTIVE`) — best-effort on terminals that
  report cell-motion mouse events; keyboard navigation is the
  documented fallback. Keyboard-selected rows keep their `C_ACTIVE`
  highlight regardless of hover state.

**Colour palette.** All styles live in
[`bridge/launcher/palette.py`](../bridge/launcher/palette.py) and are
shared with the in-game popup. Roles:

| Name           | Role                                              |
|----------------|---------------------------------------------------|
| `C_TITLE`      | Page banners, ASCII logo, section titles          |
| `C_ACTIVE`     | Focused/selected row, emphasis in prompts         |
| `C_ITEM`       | Inactive selectable menu rows                     |
| `C_HOVER`      | Mouse-hovered row (between `C_ITEM` and `C_ACTIVE`) |
| `C_BODY`       | Body text — About prose, script summaries         |
| `C_HINT`       | Footer nav hints, secondary prompt labels         |
| `C_QUOTE`      | Italic quote text on the main menu                |
| `C_QUOTE_ATTR` | Quote attribution line (sage green)               |
| `C_ACCENT`     | Call-to-action rows, script alias headings        |
| `C_YELLOW`     | Warnings (non-fatal errors, can't-delete notices) |
| `C_ERR`        | Hard errors                                       |

**Alignment convention (Profile / Options / Scripts pages).** Menu rows
are left-aligned on a shared column inside a centred block. The widest
label is computed on every render so the block re-centres after a
resize.

**About page three-colour scheme.** Each wrapped line is classified
before printing: all-uppercase lines → `C_TITLE` (headings); lines
starting with whitespace → `C_ACCENT` (key/command lines such as
`  cp -e`); all other non-empty lines → `C_BODY` (prose). Indented lines
pass through `_wrap_text` unchanged.

- **Alt screen / cursor / mouse modes.** `Application(full_screen=True,
  mouse_support=True)` manages alt-screen entry and exit, cursor
  visibility, and mouse-mode toggles itself. No manual ANSI escape
  sequences are emitted by the launcher.
- **Resize.** prompt_toolkit invalidates the layout on SIGWINCH; every
  text function reads terminal dimensions afresh, so the centred block
  recentres immediately.
- **One-second refresh.** `refresh_interval=1.0` drives periodic
  re-renders so the version-cache mtime check, session-status re-probe,
  and About update-available line track external state without a
  keypress.
- **ttimeoutlen / timeoutlen.** Both lowered to 50 ms so bare ESC fires
  near-instantly instead of waiting prompt_toolkit's 500 ms
  disambiguation timeout (same tuning as the popup).
- **Handoff via `os.execvp`.** The Enter-game dispatch records a
  deferred exec command, calls `app.exit()`, and then the main entry
  runs `os.execvp(...)` after `run_async` returns — so prompt_toolkit
  has a chance to restore the terminal before tmux or the new launcher
  takes over. The launcher → `tmux_start.sh` handoff itself is
  `execvp`'d, so there is no intermediate bash flash between menu and
  cockpit.

**Initial layout build.** `bridge/launcher/build_initial_layout.sh` is invoked in one of two modes, chosen by `bridge/launcher/tmux_start.sh` based on whether `LAUNCHER_COLS` / `LAUNCHER_ROWS` are set in the environment. In both modes the script splits panes, applies divider styling, and finally touches `bridge/runtime/.layout_ready`; meanwhile pane 0 runs `bridge/launcher/wait_for_layout.sh`, which polls `.layout_ready` at 50 ms intervals (2 s timeout) and then execs `tt++`. The sentinel handshake guarantees tt++ starts only after the layout is in place, so the first lines of tt++/Lua output are never lost into scrollback.
- **Pre-attach build (launcher path).** When `tmux_start.sh` is invoked from `launcher.py` the launcher exports `LAUNCHER_COLS` and `LAUNCHER_ROWS` from `prompt_toolkit`'s known terminal size — it just rendered a full-screen UI, so the dimensions are authoritative. `tmux_start.sh` then creates the detached session with explicit `-x` / `-y`, runs `build_initial_layout.sh` synchronously against the detached session, and only then calls `tmux attach`. The user sees a single frame transition from launcher to a fully-built cockpit — no visible cascade of pane splits.
- **Post-attach build (fallback).** Without the env vars (`--no-menu`, Windows shortcut → `bridge/launcher/launch.sh`), there is no reliable pre-attach dimension source: `stty size` is stale on terminals that haven't synced their PTY size when bash starts. `tmux_start.sh` registers a one-shot `client-attached` hook that fires `build_initial_layout.sh` after the first client attaches, at which point `tmux display-message -p '#{window_width}'` is authoritative. The script disarms its own hook on completion via `tmux set-hook -u client-attached` (idempotent — a no-op in the pre-attach path). The brief single-pane state after attach is visible but acceptable; see ADR 0041 for the full rationale that still governs this path.

`build_initial_layout.sh` itself is idempotent in both modes — a `PANE_COUNT > 1` guard at the top makes detach/re-attach a no-op. Its dimension source block prefers the env vars when present and falls back to `tmux display-message` otherwise, so the same script services both paths.

**Ctrl+C hardening (ui/dev panes).** Focusing a UI or DEV pane and pressing Ctrl+C would send SIGINT to the `tail -f` foreground process, kill it, and close the pane — breaking the layout for inexperienced users. Both panes are now launched with a hardened wrapper:

```
bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f <PATH>; printf "\n[pane kept alive — use cp-u/cp-d to close]\n"; sleep 0.2; done'
```

`stty -isig` disables signal generation (INTR/QUIT/SUSP) for the pane's tty, so Ctrl+C never produces SIGINT in the first place. `trap "" INT` is a belt-and-braces fallback in case stty is unavailable. The `while true` loop restarts `tail -f` if it exits for any other reason (log rotation, truncation). The input pane (`python3 bridge/panes/input_pane.py`) is deliberately unwrapped — it needs signals to function correctly.

---
Back to [architecture.md](../architecture.md).
