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
                                             restores channels at load
                                                        │
                                             lua/core/comm_store.lua
                                             wraps Comm.Channel.Text;
                                             appends to per-profile JSONL;
                                             seeds history at load from
                                             archive (7-day window)
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
wrap-and-call pattern as `status_state.lua`. `lua/core/comm_store.lua` loads
last (alphabetical: `comm_state` < `comm_store`) and wraps `Comm.Channel.Text`
a second time to append each new message to the per-profile archive.

### State flow

After either wrapped handler runs, `serialize()` writes `bridge/comm.state`
atomically (tmp + rename). `bridge/comm_pane.py` polls via mtime every 250 ms
and redraws on change. `SIGWINCH` is forwarded via signal handler; the app
calls `invalidate()` to trigger a redraw.

### cp -r persistence

History is restored by `comm_store.lua` from the per-profile JSONL archive
(see **Per-profile archive** below), clamped to `max_size` (1000). Channel
state is restored by `comm_state.lua`'s `_load_state_file()`, which reads
`bridge/comm.state` and repopulates `state.comm.channels` (name + caption
only; label is re-derived). After channels load, `serialize()` is called once
to write a well-formed file; after `comm_store.lua` seeds history it calls
`state.comm.serialize()` again so the pane picks up the full history on its
next 250 ms poll. This means channel header and history reappear immediately
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
with a computed `label` field. The `label` field is kept for backward compatibility
but is **no longer consulted by the renderer** — the pane uses `CHANNEL_LABELS`
(hardcoded 2–3 char abbreviations) instead.

**`history`** — full `state.comm.history`, including ANSI codes verbatim in the
`text` field. dkjson encodes `\x1b` as ``; Python's json module decodes it
back to the ESC byte; prompt_toolkit's `ANSI()` class then converts it to styled
fragments.

## Header labels

Labels are hardcoded 2–3 character abbreviations in `CHANNEL_LABELS` at the top
of `bridge/comm_pane.py`. Unknown channels fall back to `channel[:2].capitalize()`.

| Channel   | Label |
|-----------|-------|
| tales     | Na    |
| tells     | Te    |
| says      | Sa    |
| yells     | Ye    |
| prayers   | Pr    |
| emotes    | Em    |
| whispers  | Wh    |
| questions | Qu    |
| songs     | Son   |
| socials   | Soc   |

Header order is fixed by the `CHANNEL_LABELS` declaration order (Na Te Sa Ye Pr Em
Wh Qu Son Soc), filtered against the channels actually advertised by the server
(`state["channels"]`). Any channels the server advertises that are not in
`CHANNEL_LABELS` are appended at the end in `Comm.Channel.List` order with the
`name[:2].capitalize()` fallback label — so the header stays correct if MUME ever
adds a new channel.

The old label-collision algorithm (first unused uppercase character of the channel
name) is retired. The `label` field emitted by Lua into `comm.state` is preserved
for backward compatibility but is not read by the renderer.

## Filter persistence

Filter state lives in `bridge/comm_filters.conf` (gitignored), owned entirely by
`comm_pane.py`. Lua does not read or write this file.

Format: one `name=true|false` line per explicitly-set channel. Missing key means
enabled (sparse-map semantics, default-on for new channels).

`comm_pane.py` loads the file at startup via `_load_filters()`. On every toggle,
`_save_filters()` writes atomically (tmp + rename). No tt++ involvement — toggling
a filter is entirely silent; nothing appears in the game pane.

See [docs/decisions/0010-comm-filter-persistence.md](decisions/0010-comm-filter-persistence.md).

## Per-profile archive

`lua/core/comm_store.lua` maintains a durable, per-profile JSONL file at:

```
logs/comm_archive/<profile>.jsonl
```

`<profile>` is resolved at brain startup by parsing `bridge/startup.conf` for
the `profile=` key; falls back to `"default"` if the key is absent or the file
is missing.

### File format

One JSON object per line (JSONL). Each line is an entry with the same schema as
`state.comm.history`:

```json
{"ts":1714000000,"channel":"narrates","talker":"Aragorn","talker_type":"ally","destination":null,"text":"with preserved ANSI codes"}
```

ANSI escape sequences in `text` are stored verbatim (dkjson encodes `\x1b` as
``; it round-trips correctly through both dkjson and Python's json module).

### 7-day retention

At brain startup, `comm_store.lua` reads the archive and discards any entry with
`ts < os.time() - 604800` (7 days). The pruned set is atomically rewritten via
`tmp + rename` before history is seeded. Pruning is O(n) and happens once per
brain start.

### History seeding

After pruning, the filtered entries are clamped to `state.comm.max_size` (1000,
keeping the most recent) and assigned to `state.comm.history`. Then
`state.comm.serialize()` is called once so `bridge/comm.state` reflects the
seeded history before the pane's next 250 ms poll.

`comm_state.lua` owns `bridge/comm.state` and channel restore; it does **not**
seed history. This split is deliberate: the archive is the authoritative source
of truth for history across restarts; `bridge/comm.state` is a derived
projection used only by the pane renderer.

### Append path

Each new `Comm.Channel.Text` event appends one JSON line to the archive
(open-append, write, close). No tmp+rename — JSONL truncation on a partial
write is recoverable: the trailing partial line is silently skipped on the next
startup read.

### Storage bound

Archive size is bounded by message activity within the 7-day window. In
practice sub-MB. The `logs/` tree is gitignored.

### Profile isolation

Each profile gets its own file. Switching profiles via the launcher starts a
fresh brain process; `comm_store.lua` resolves the new profile name and reads
only that file. Other profiles' archives are never read or modified.

See [docs/decisions/0011-per-profile-comm-archive.md](decisions/0011-per-profile-comm-archive.md).

## comm_pane.py

`bridge/comm_pane.py` — prompt_toolkit `Application(full_screen=True,
mouse_support=True)`.

### Layout

`HSplit([header_window, list_window, indicator_container])`. Header height
fixed at 1. List fills remaining rows. `indicator_container` is a
`ConditionalContainer` keyed off `_scroll_offset > 0` — it occupies 1 row
below the list only when there are hidden newer messages, and disappears
completely otherwise. Because the indicator lives in its own `Window`, list
`wrap_lines=True` can never clip it.

### Header

Format: ` Na Te Sa Ye Pr Em Wh Qu Son Soc ` (single leading inert space, label,
space after each label). Iteration order is `CHANNEL_LABELS` declaration order,
filtered against channels advertised in `state["channels"]`; unknown channels
appended in server order. See **Header labels** above.

`FormattedTextControl` with `(style, text, mouse_handler)` tuples. One fragment
per label + one inert space fragment after each, plus a leading inert space.
Foreground colour indicates filter state:

| State    | Style                                  |
|----------|----------------------------------------|
| Enabled  | `CHANNEL_COLORS[name]` — channel color |
| Disabled | `C_LABEL_OFF` — `fg:#3a3a3a` grey      |

No background color. Each label fragment's mouse handler calls
`forward_toggle(channel.name)` on `MouseEventType.MOUSE_DOWN`.

`forward_toggle(name)` flips `_filters[name]`, calls `_save_filters()`, and
calls `_app.invalidate()`. No subprocess, no tmux, no tt++ involvement.

Using `MOUSE_DOWN` (rather than `MOUSE_UP`) means toggling fires on the press
event. This eliminates missed clicks caused by press and release landing on
different fragments.

Right-click solos a channel: every other advertised channel is disabled,
leaving only the clicked one. A second right-click on the same label restores
the filter state that was active before solo was entered. Right-clicking a
different label while in solo mode switches the soloed channel without losing
the original snapshot. A left-click while soloed drops the snapshot and resumes
normal manual filtering.

Solo state is runtime-only — it is not persisted to `comm_filters.conf`. The
post-solo filter values *are* persisted (each channel's enabled/disabled state
writes through normally), so a process restart while soloed leaves the snapshot
lost.

### List

The list `Window` has `wrap_lines=True` so long messages soft-wrap rather than
truncating. `_list_text()` uses a wrap-aware bottom-up selection: given
`anchor_idx = total - 1 - _scroll_offset`, it walks backward from the anchor
accumulating wrapped display rows (via `_row_count`) until the window is filled
or index 0 is reached. The anchor entry is always included even when it alone
exceeds `list_height` — the surplus falls off the top (clip-top semantics). The
`Window` passes `get_vertical_scroll=_anchor_bottom`, which pins the rendered
content's bottom row to the window's bottom edge, so the newest included message
is always visible at the bottom, never obscured by prompt_toolkit's default
top-anchor scroll.

Row format depends on channel class (see **Display normalization** below):

- **Quoted channels:** `HH:MM <Talker> <verb> [destination] '<message>'`
- **Action channels:** `HH:MM <text>` (talker-prefix color split, no verb)

| Field       | Style                                      | Notes                                                    |
|-------------|--------------------------------------------|---------------------------------------------------------|
| HH:MM       | `C_TIME` — `fg:#687685`                    | From `ts`; renders as DD/MM for messages older than 24 h |
| Talker      | `C_TALKER_YOU` or `C_TALKER_OTHER`         | `C_TALKER_YOU` (soft cyan) when `talker == "you"`; `C_TALKER_OTHER` (warm tan) otherwise; first char capitalized |
| verb        | `CHANNEL_COLORS[channel]`                  | From `CHANNEL_VERBS` (self/other form); unknown → channel name |
| destination | `C_TALKER_YOU` or `C_TALKER_OTHER`         | `C_TALKER_YOU` when `destination == "you"`; `C_TALKER_OTHER` otherwise; present only when non-empty |
| message     | `C_MESSAGE_SELF` or `C_MESSAGE_OTHER`      | Extracted from `text` (see Display normalization); ANSI preserved |

Talker-type (`ally`/`enemy`/`neutral`/`npc`) coloring has been removed. Talker
color is now purely self vs other.

### Scroll semantics

`_scroll_offset` integer: **0 = bottom (live-follow)**. Increasing values hide
that many messages at the bottom.

| Event                         | Effect                                                                          |
|-------------------------------|---------------------------------------------------------------------------------|
| Mouse wheel up on list        | `_scroll_offset += 1` (wrap-aware cap — see below)                             |
| Mouse wheel down on list      | `_scroll_offset -= 1` (floor at 0)                                              |
| New messages while offset > 0 | `_scroll_offset += delta` (sticky view)                                         |
| Click `↓ N newer messages`    | `_scroll_offset = 0` (jump to bottom)                                           |
| Filter flip                   | `_scroll_offset` clamped to `[0, total-1]` on next render                       |

Mouse wheel scroll is handled by `ListControl`, a `FormattedTextControl`
subclass that overrides `mouse_handler`. On `SCROLL_UP`/`SCROLL_DOWN` events
not consumed by the base class, it adjusts `_scroll_offset` and calls
`_app.invalidate()`. The previous `@kb.add("<scroll-up>")` / `<scroll-down>`
key bindings were no-ops and have been removed.

**Wrap-aware `max_offset`** — on each scroll-up tick the handler walks forward
from `filtered[0]`, accumulating wrapped display rows via `_row_count`. The
smallest index `i` at which the running sum reaches `list_height` gives
`max_offset = total - 1 - i`. This means scrolling all the way up pins the
oldest message at the top of the window, with no blank rows above it. If the
entire history fits within `list_height` rows, `max_offset = 0` (no scrolling
possible).

When `_scroll_offset > 0`, a dedicated indicator row appears **below** the list
(not inside it):

```
↓ N newer messages
```

in `C_INDICATOR` style (amber, italic — reads as system meta-information, not
chat content). It is rendered by `_indicator_text()` inside its own
`ConditionalContainer / Window`, so list `wrap_lines=True` can never push it
off the bottom. Clicking it (`MOUSE_DOWN`) resets offset to 0.

### Colour palette

All constants are defined at the top of `bridge/comm_pane.py`:

| Constant          | Value                   | Role                                                        |
|-------------------|-------------------------|-------------------------------------------------------------|
| `C_TIME`          | `fg:#687685`            | Timestamp — muted blue-grey (104,118,133), recedes visually |
| `C_TALKER_YOU`    | `fg:#afd2d2`            | "you" as talker or destination — soft cyan, no bold         |
| `C_TALKER_OTHER`  | `fg:#c2a878`            | Talker/destination for other players/NPCs — warm tan        |
| `C_MESSAGE_SELF`  | `fg:#c3e6e9`            | Message text when self                                      |
| `C_MESSAGE_OTHER` | `fg:#91bec1`            | Message text from others                                    |
| `C_LABEL_OFF`     | `fg:#3a3a3a`            | Header label when filter off                                |
| `C_INDICATOR`     | `fg:#d4a04e italic`     | ↓ N newer messages                                          |

Per-channel verb/label colors are in `CHANNEL_COLORS` (see top of file).

### Display normalization

`bridge/comm_pane.py` normalizes raw GMCP payloads at render time. Raw data in
`state.comm.history`, `comm.state`, and the JSONL archive is untouched.

**Channel classes** — the renderer dispatches on two sets:

```python
QUOTED_CHANNELS   = {"tales", "tells", "says", "yells", "whispers",
                     "prayers", "songs", "questions"}
ACTION_CHANNELS   = {"emotes", "socials"}
DIRECTED_CHANNELS = {"tells", "whispers"}
```

Unknown channel names default to quoted-style rendering with the channel name as
the fallback verb.

**Verb table (`CHANNEL_VERBS`)** — two forms per channel: self (used when
`talker == "you"`) and other. Action channels have entries in the table but their
verbs are not used at render time.

| Channel   | Self form | Other form |
|-----------|-----------|------------|
| tales     | narrate   | narrates   |
| tells     | tell      | tells      |
| says      | say       | says       |
| yells     | yell      | yells      |
| whispers  | whisper   | whispers   |
| prayers   | pray      | prays      |
| songs     | sing      | sings      |
| questions | ask       | asks       |

Unknown channels fall back to the channel name as both forms.

**Quoted-channel rendering** (`_render_quoted_row`) — format:
`HH:MM <Talker> <verb> [destination] '<message>'`

- Message body extracted from `text`: substring between the *first* `'` and the
  *last* `'`. Falls back to `text` verbatim if no two quotes found. When
  `talker == "you"`, `text` is already the bare message — wrap directly.
- **Destination fallback** — MUME omits the `destination` field on incoming
  tells and whispers. If `destination` is absent and `channel` is in
  `DIRECTED_CHANNELS` (`tells`, `whispers`) and `talker != "you"`, the renderer
  fills in `destination = "you"` before display. This covers the common case of
  `"Gibur tells you 'np :)'"` arriving with no destination in the payload.
- **`DESTINATION_PREPOSITIONS`** — some channels require a preposition between
  the verb and the destination. The table is `{"whispers": "to"}`. When a channel
  has an entry, the preposition is inserted as a separate fragment in `verb_style`
  before the destination fragment. Channels with no entry take the destination as
  a direct object (no preposition). Examples:
  - `You whisper to Dori the armourer 'hej'` (preposition inserted)
  - `You tell Ibuki 'come to the inn'` (no preposition — tells not in table)
- **Destination** — when `destination` is present (or filled by the fallback),
  it is inserted between verb (and preposition, if any) and message in
  `C_TALKER_YOU` when the value is `"you"`, `C_TALKER_OTHER` otherwise.
  Capitalization: `"you"` stays lowercase; any other value has its first character
  uppercased. Examples:
  - `You tell Ibuki 'come to the inn'`
  - `Frodo tells you 'hi there'`
  - `Gibur tells you 'np :)'` (destination absent in payload; fallback applied)
  - `You ask Aragorn 'where is the nearest inn'`

**Action-channel rendering** (`_render_action_row`) — format: `HH:MM <text>`

No channel verb and no separately-rendered talker fragment. `text` from the GMCP
payload is rendered verbatim with a talker-prefix color split. Detection runs in
priority order:

1. If `text.startswith("You ")`: render as self — `"You "` in `C_TALKER_YOU`,
   remainder in `C_MESSAGE_SELF`. The `talker` field is ignored; MUME may set it
   to the character name for own socials rather than `"you"`.
2. Else if `talker` is non-empty and `text.lower().startswith(talker.lower() + " ")`:
   render as other — slice the matching prefix from `text` (preserving `text`'s
   original casing, case-insensitive match) in `C_TALKER_OTHER`, remainder in
   `C_MESSAGE_OTHER`. Covers multi-word talker names and talker/text case
   mismatches (e.g. `talker="a dwarven sergeant"`, `text="A dwarven sergeant …"`).
3. Else (malformed — talker not at start of `text`): prepend `<Talker> ` in
   talker color (`"you"` → `"You"`), then render `text` verbatim in message
   color.

This eliminates double-talker artifacts such as `"You social You wave goodbye."` or
`"Vainamoinen emotes Vainamoinen smiles warmly."` that arise when the channel verb
is prepended to a `text` field that already embeds the talker.

Embedded ANSI in the message portion is preserved via
`prompt_toolkit.formatted_text.ANSI()`. The configured `C_MESSAGE_*` color is
applied as the default for plain (non-ANSI-styled) text.

**Talker capitalization** — first character of `talker` is uppercased; internal
case is preserved (e.g. `"Vit the innkeeper"` stays `"Vit the innkeeper"`).
`"you"` → `"You"`.

### Dev fixture

`bridge/dev/comm.state.fixture` is a static JSON file covering all ten channels
in self and other form. Two env vars override the live paths:

| Variable           | Default                              | Purpose                         |
|--------------------|--------------------------------------|---------------------------------|
| `COMM_STATE_PATH`  | `bridge/comm.state`                  | State file the pane polls       |
| `COMM_FILTERS_CONF`| `bridge/comm_filters.conf`           | Filter persistence file         |

Usage:

```sh
COMM_STATE_PATH=bridge/dev/comm.state.fixture \
COMM_FILTERS_CONF=/tmp/comm_filters.fixture.conf \
python3 bridge/comm_pane.py
```

Point `COMM_FILTERS_CONF` at `/tmp` so toggling in fixture mode does not touch the
real config. See `bridge/dev/README.md` for edge cases covered by the fixture.

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

The 29-column `RIGHT_MIN` floor in `on_window_resize.sh` and `apply_layout.sh`
is driven by the `status` pane's minimum render width. The comm pane has no
fixed column requirement — it adapts to available width.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -m`                           | `toggle_pane.sh comm` (runtime only)            |
| In-game popup → Options           | `toggle_pane.sh comm --persist`                 |
| Launcher Options → Comm pane      | `_save_conf` → `startup.conf show_comm`         |

Persistence key: `show_comm` in `bridge/startup.conf`. Fresh-install default
is `1` (comm pane on). Existing `startup.conf` files that lack `show_comm`
fall through to the runtime `${show_comm:-0}` guard — existing installs see
no change.

---
Back to [architecture.md](../architecture.md).
