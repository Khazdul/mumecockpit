# Launcher

Pre-tmux startup menu, rendering conventions, and the exec-chain that starts
or returns to the cockpit. Touch this file when changing launcher pages,
rendering behaviour, the startup command-line options, or the return-to-menu
flow.

## Startup

```bash
./start.sh            # show retro startup menu (default)
./start.sh --no-menu  # skip menu, use current bridge/startup.conf
./start.sh -d         # skip menu, force dev pane on for this run (not persisted)
./start.sh -u         # skip menu, force UI pane on for this run (not persisted)
```

`start.sh` is a thin wrapper that installs dependencies and then:
- Without bypass flags → `exec bash bridge/launcher.sh` (startup menu)
- With `--no-menu` / `-d` / `-u` → `exec bash bridge/tmux_start.sh` (direct start)

The return-to-menu path (in-game popup "Exit to main menu") is handled by an
exec-chain inside `tmux_start.sh`: after `tmux attach` returns, the script
checks for `bridge/.return_to_menu` (written by `ingame_menu.sh` just before
firing `cp -e`) and, if present, `exec`s back into `bridge/launcher.sh`.
No intermediate bash frame — no flash. `tmux_start.sh` also clears any stale
sentinel at the top of each run so a crash cannot mis-route a subsequent cold
start.

## Startup menu (`bridge/launcher.sh`)

A DOS-style retro menu rendered in the terminal before tmux launches.
Pure bash + ANSI escapes; no external dependencies beyond coreutils.

| Feature | Detail |
|---------|--------|
| Session detect | `tmux has-session -t mume` + `list-clients` → top item is "New session", "Continue session", or "Mirror session (attached elsewhere)" |
| Profile page | Lists `ttpp/sessions/*.tin`; select, create (blank / copy from existing), delete. `default` cannot be deleted. Selected profile is written to `startup.conf` and consumed by `ttpp/core/config.tin` at tt++ startup (Phase 2). |
| Options page | Toggle Character pane / Comm pane / UI / Dev / Input panes; Pane dividers; connection mode; live layout mockup (updates on toggle). Fresh-install defaults: status, comm, ui, input on; dev off. Content hides progressively at small heights: descriptions → mockup → section headings; menu items always render |
| Scripts page | Reads `bridge/scripts.cache`; scrollable |
| About page | Reads `bridge/about.txt`; word-wrapped, cached per resize, scrollable |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/startup.conf` on Back / ESC |

## Rendering conventions

Launcher pages render through `render_frame` in `bridge/menu_render.sh`.
Rules are strict — deviations reintroduce flicker or scroll artifacts:

**Semantic colour palette (`bridge/menu_render.sh`).** All escape codes are
referenced by role, not raw colour, so visual adjustments stay localised:

| Name            | Role                                               |
|-----------------|----------------------------------------------------|
| `_MR_TITLE`     | Page banners, ASCII logo, section titles           |
| `_MR_ACTIVE`    | Focused/selected row, emphasis in prompts          |
| `_MR_ITEM`      | Inactive selectable menu rows                      |
| `_MR_SECTION`   | Section headings inside pages (quieter than items) |
| `_MR_BODY`      | Body text — About prose, script summaries          |
| `_MR_HINT`      | Footer nav hints, secondary prompt labels          |
| `_MR_QUOTE`     | Italic quote text on the main menu                 |
| `_MR_QUOTE_ATTR`| Quote attribution line (sage green)                |
| `_MR_ACCENT`    | Call-to-action rows, script alias headings         |
| `_MR_DESC`      | Pane-description text in layout mockup             |
| `_MR_YELLOW`    | Warnings (non-fatal errors, can't-delete notices)  |
| `_MR_ERR`       | Hard errors                                        |

**Alignment convention (Profile / Options pages).** Menu rows are
left-aligned on a shared column inside a centred block. The widest label
is found on every render so the block re-centres correctly after terminal
resize. `draw_menu_item` accepts an optional `pad_override` (third arg) to
override its default per-row centering, and an optional `inactive_color`
(fourth arg) to colour a row differently in its inactive state (used for
the amber "[+] Create new profile" row).

**About page three-colour scheme.** `_render_about` classifies each wrapped
line before printing: all-uppercase lines → `_MR_TITLE` (headings); lines
starting with whitespace → `_MR_ACCENT` (key/command lines such as
`  cp -r`); all other non-empty lines → `_MR_BODY` (prose). Indented lines
pass through `wrap_text` unchanged — a leading-whitespace guard flushes the
current word-wrap buffer and emits the line verbatim, preserving command
column alignment.

- **Alt screen buffer.** Enter on launch (`\e[?1049h`), leave on exit. Cleared
  automatically when tmux attaches.
- **Cursor hidden** (`\e[?25l`) except during profile name entry.
- **Mouse + alt-scroll disabled** (`\e[?1000l \e[?1002l \e[?1003l \e[?1006l
  \e[?1007l`) while launcher is active. Restored on exit.
- **No full clear between frames.** `render_frame` overwrites cell-by-cell:
  `\e[H` home, each line followed by `\e[K`, `\e[J` at end. Never `\e[2J`.
- **No trailing newline** after the last line of any frame — it scrolls the
  terminal and jitters the title/footer row.
- **Dirty-flag redraw.** Main loop uses `_DIRTY=1` set by a `WINCH` trap,
  state-changing key handler, or by the cache-mtime poll when
  `bridge/version.cache` is updated mid-session; `read -rsn1 -t 0.2` yields
  fast enough resize response without a busy loop.
- **Handoff via `exec`.** Launcher → tmux_start.sh uses `exec bash …`; the
  tmux session is created and then attached with a plain `tmux attach` (not
  exec, so the return-to-menu sentinel check can run after attach exits).
  The launcher → tmux_start handoff itself is exec'd, so there is no
  intermediate bash flash between menu and cockpit.

**Pane-setup barrier.** `bridge/tmux_start.sh` prefixes the tt++ launch command with `sleep 0.3 &&` so that `tmux split-window` and `tmux resize-pane` complete before tt++/Lua begin writing to `ui.log` / `debug.log`. Without the barrier, `tail -f` in the UI/DEV panes reflows mid-output and the first emitted lines are swallowed into scrollback.

**Ctrl+C hardening (ui/dev panes).** Focusing a UI or DEV pane and pressing Ctrl+C would send SIGINT to the `tail -f` foreground process, kill it, and close the pane — breaking the layout for inexperienced users. Both panes are now launched with a hardened wrapper:

```
bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f <PATH>; printf "\n[pane kept alive — use cp-u/cp-d to close]\n"; sleep 0.2; done'
```

`stty -isig` disables signal generation (INTR/QUIT/SUSP) for the pane's tty, so Ctrl+C never produces SIGINT in the first place. `trap "" INT` is a belt-and-braces fallback in case stty is unavailable. The `while true` loop restarts `tail -f` if it exits for any other reason (log rotation, truncation). The input pane (`python3 bridge/input_pane.py`) is deliberately unwrapped — it needs signals to function correctly.

---
Back to [architecture.md](../architecture.md).
