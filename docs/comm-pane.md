# Communication Pane

The comm pane is a right-column tmux pane positioned between `status` and `ui`
(top to bottom: status → comm → ui → dev). It displays `state.comm.history` with
a one-row click-to-toggle channel-filter header. Touch this file when changing
the renderer, the state-file schema, filter persistence, scroll semantics, or
the width-responsive header layout.

## Architecture

```
Comm.Channel.Text ──► lua/core/comm_log.lua ──► state.comm.history
Comm.Channel.List ──► lua/core/comm_log.lua ──► state.comm.channels
                                                        │
                                             lua/core/comm_state.lua
                                             wraps both handlers;
                                             serialises history + channels
                                             to bridge/runtime/comm.state (JSON);
                                             restores channels at load
                                                        │
                                             lua/core/comm_store.lua
                                             wraps Comm.Channel.Text;
                                             appends to per-character JSONL;
                                             seeds history on Char.Name from
                                             archive (7-day window)
                                                        │
                                            mtime change │  250 ms poll
                                                        ▼
                                          bridge/panes/comm_pane.py
                                          prompt_toolkit full-screen
                                          Application with mouse_support
                                                        │
                                          reads/writes  │
                                                        ▼
                                          bridge/runtime/comm_filters.conf
```

### Load order and event subscriptions

`lua/core/comm_log.lua` is the primary writer for `Comm.Channel.Text` and
`Comm.Channel.List` — it owns `gmcp.handlers` for both and writes
`state.comm.history` / `state.comm.channels`. After the primary writer runs,
`gmcp.dispatch` emits `gmcp_comm_channel_text` or `gmcp_comm_channel_list`.

`lua/core/comm_state.lua` (loads after `comm_log`, alphabetical) subscribes to
both events and calls `serialize()` to write `bridge/runtime/comm.state`. It exposes
`state.comm.serialize` so `comm_store.lua` can trigger a re-serialise after
seeding history.

`lua/core/comm_store.lua` (loads after `comm_state`, alphabetical) subscribes
to `gmcp_comm_channel_text` to append each new message to the per-character
JSONL archive. It also subscribes to `gmcp_char_name` to seed history from the
archive on login. Subscription order ensures `comm_state`'s serialize runs
before `comm_store`'s archive append.

### State flow

After the primary writer and subscribers run, `bridge/runtime/comm.state` is written
atomically (tmp + rename). `bridge/panes/comm_pane.py` polls via mtime every
250 ms and redraws on change. `SIGWINCH` is forwarded via signal handler; the
app calls `invalidate()` to trigger a redraw.

### Cross-launch persistence

History is restored by `comm_state.lua`'s `_load_state_file()`, which reads
`bridge/runtime/comm.state` at brain startup and repopulates
`state.comm.history` and `state.comm.channels` (name + caption only; label
is re-derived). After channels and history load, `serialize()` is called
once so the pane picks up both on its next 250 ms poll. Filter state is
restored independently: `comm_pane.py` reads `comm_filters.conf` at
startup.

### Disconnect policy

`state.comm.history` is **not** cleared on `SESSION DISCONNECTED`. Channel
history is retained across reconnects within the same brain process. This
diverges from `status_pane`, which blanks on disconnect because its
fields have meaningful null states. Communication history is purely
append-only log data with no meaningful null state.

## comm.state schema

JSON, atomic write (tmp + rename), gitignored. Filter state is **not** included
— it lives separately in `comm_filters.conf` (see **Filter persistence** below;
no longer owned by `comm_pane.py` alone — the launcher and popup write it too).
The file also serves as a load-time cache: `comm_state.lua` reads it at startup
to repopulate history and channels for cross-launch continuity.

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
but is **no longer consulted by the renderer** — the pane derives header text via
the `CHANNEL_DISPLAY` → `caption` → `name.title()` chain, then truncates evenly to
fit the current pane width (see **Header labels** below).

**`history`** — full `state.comm.history`, including ANSI codes verbatim in the
`text` field. dkjson encodes `\x1b` as ``; Python's json module decodes it
back to the ESC byte; prompt_toolkit's `ANSI()` class then converts it to styled
fragments.

## Header labels

Labels are derived per render pass and abbreviated to fit the current pane
width. There is no curated table of short codes; only declaration order and a
sparse display-name override map are kept at the top of
`bridge/panes/comm_pane.py`.

**Display-name resolution.** For each advertised channel the renderer picks the
first non-empty value of:

1. `CHANNEL_DISPLAY[name]` — sparse override map, currently
   `{"tales": "Narrates"}`. Use this only when the visible label must differ
   from both the GMCP name and the server-provided caption.
2. `caption` field from `state["channels"]` (e.g. `"Tells"`, `"Says"`).
3. `name.title()` — last-resort fallback for channels with no caption.

The override is **display-only**: `CHANNEL_COLORS`, `CHANNEL_VERBS`, the
filter/solo handlers, and `comm_filters.conf` all stay keyed on the GMCP
channel name. Renaming a channel for display does not change any of its
behaviour.

**Channel order.** The fixed order comes from the `CHANNEL_ORDER` list
(formerly the keys of the retired `CHANNEL_LABELS` dict): `tales`, `tells`,
`says`, `yells`, `prayers`, `emotes`, `whispers`, `questions`, `songs`,
`socials`. It is filtered against the channels actually advertised by the
server (`state["channels"]`); any channel the server advertises that is not in
`CHANNEL_ORDER` is appended at the end in `Comm.Channel.List` order.

**Width-responsive layout (`_header_layout(caps, W)`).** Given the resolved
display names and the available column count `W`:

```
N = len(caps)
if W - (N - 1) >= N:        # >= 1 char per cell, with separators
    sep, budget, visible = 1, W - (N - 1), N
elif W >= N:                # 1 char per cell, no separators
    sep, budget, visible = 0, W, N
else:                       # cannot fit all channels at 1 char each
    sep, visible = 0, W     # render first W channels, drop the rest
    budget = visible

target = budget // visible
rem    = budget %  visible
if target >= max(len(caps[i]) for i in range(visible)):
    cell_w[i] = len(caps[i])              # natural, tight
else:
    cell_w[i] = target + (1 if i < rem else 0)
```

Each cell is `caps[i][:cell_w[i]]` left-justified and space-padded to
`cell_w[i]`. Cells join with `sep` space(s). Total visible width is `W` or
less by construction — the header never needs horizontal clipping.

This produces five regimes as the pane narrows:

| Width                | Result                                                      |
|----------------------|-------------------------------------------------------------|
| Plenty of room       | Full display names, single space between cells              |
| Tighter              | Uniform prefix truncation (lengths differ by at most one)   |
| Single-char + space  | One char per channel, single space between                  |
| Single-char only     | One char per channel, no separators                         |
| Below that           | Trailing channels drop off; the first `W` channels remain   |

`_header_layout()` in the code is authoritative if anything above disagrees.

**Accepted trade-offs.** No uniqueness logic across short prefixes — two
channels can collide on a single starting letter at the narrowest widths (e.g.
`S` for both `says` and `songs`). Channels dropped from the header at extreme
narrowness reappear when the pane widens; filter and solo state are
independent of header visibility, so a dropped channel's filter still
suppresses its messages.

## Filter persistence

Filter state lives in `bridge/runtime/comm_filters.conf` (gitignored). Lua does
not read or write this file; tt++ is never involved. `comm_pane.py` reads and
writes it, but is no longer the sole writer — the in-game popup and launcher
(`bridge/launcher/comm_channels.py`) also write it, and the pane picks up those
edits live (see **Live re-read** below).

Format: one `name=true|false` line per explicitly-set channel. Missing key means
enabled (sparse-map semantics, default-on for new channels).

`comm_pane.py` loads the file at startup via `_load_filters()` (which clears
`_filters` first, so startup and the live re-read share one clean-load path). On
every toggle, `_save_filters()` writes atomically (tmp + rename) and stamps
`_filters_mtime` with the post-write mtime so the poll loop does not re-process
the pane's own write. No tt++ involvement — toggling a filter is entirely
silent; nothing appears in the game pane.

### Header preference

`bridge/runtime/comm_prefs.conf` (gitignored) carries a single key,
`show_header=true|false`, default `True` when the file or key is absent. It is
the cross-package contract with `bridge/launcher/comm_channels.py` (the writer);
`comm_pane.py` reads it via `_load_prefs()`. When `False`, `header_window` (a
`ConditionalContainer` keyed off `_show_header`) disappears and the list
reclaims the row — the height math in `_list_text` makes the header term
conditional so no blank row is left.

### Live re-read

The 250 ms poll loop (`_poll_state`) additionally `os.stat`s both conf files and
compares against `_filters_mtime` / `_prefs_mtime`:

- **filters mtime changed** → `_load_filters()`, drop any active solo
  (`_solo_channel = _solo_snapshot = None`, since an external edit invalidates
  the runtime-only solo snapshot — the same rule as a manual left-click while
  soloed), `app.invalidate()`.
- **prefs mtime changed** → `_load_prefs()`, `app.invalidate()`.

No new thread, file watcher, or tt++/Lua involvement — all folded into the one
existing poll. A toggle made in the in-game popup applies within one tick.

See [docs/decisions/0010-comm-filter-persistence.md](decisions/0010-comm-filter-persistence.md).

## Per-character archive

`lua/core/comm_store.lua` maintains a durable, per-character JSONL file at:

```
data/comm/<character>.jsonl
```

`<character>` is `state.char.name` as received from GMCP `Char.Name`.
The archive is initialised lazily on `Char.Name`; no file is opened at brain
startup. Switching profiles starts a fresh brain process; `Char.Name` resolves
the character key for that run.

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
`state.comm.serialize()` is called once so `bridge/runtime/comm.state` reflects the
seeded history before the pane's next 250 ms poll.

`comm_state.lua` owns `bridge/runtime/comm.state` and channel restore; it does **not**
seed history. This split is deliberate: the archive is the authoritative source
of truth for history across restarts; `bridge/runtime/comm.state` is a derived
projection used only by the pane renderer.

### Append path

Each new `Comm.Channel.Text` event appends one JSON line to the archive
(open-append, write, close). No tmp+rename — JSONL truncation on a partial
write is recoverable: the trailing partial line is silently skipped on the next
startup read.

### Storage bound

Archive size is bounded by message activity within the 7-day window. In
practice sub-MB. The `data/` tree is gitignored.

### Character isolation

Each character gets its own file under `data/comm/`. Switching profiles starts
a fresh brain process; `Char.Name` resolves the character key for that run and
only that character's file is read or written. Other characters' archives are
never touched.

See [docs/decisions/0011-per-profile-comm-archive.md](decisions/0011-per-profile-comm-archive.md).

## comm_pane.py

`bridge/panes/comm_pane.py` — prompt_toolkit `Application(full_screen=True,
mouse_support=True)`.

### Layout

`HSplit([header_window, list_window, indicator_container])`. `header_window` is
a `ConditionalContainer` keyed off `_show_header` (from `comm_prefs.conf`):
height fixed at 1 when shown, gone when hidden so the list reclaims the row.
List fills remaining rows. `indicator_container` is a `ConditionalContainer`
keyed off `_scroll_offset > 0` — it occupies 1 row below the list only when
there are hidden newer messages, and disappears completely otherwise. Because
the indicator lives in its own `Window`, it is never clipped by list content.

### Header

The header reflows to the current pane width every render. Channel display
names resolve through `CHANNEL_DISPLAY` → `caption` → `name.title()`, then
`_header_layout(caps, W)` evens out their widths and decides the separator —
see **Header labels** above for the full algorithm and the five resulting
regimes (full names → uniform truncation → single-char with spaces →
single-char no spaces → trailing-channel drop).

`FormattedTextControl` with `(style, text, mouse_handler)` tuples. Cells start
flush — no leading inert space. One clickable fragment per visible channel
whose **whole padded width** is the click target (the hit area grows with the
pane). Between cells the renderer emits one inert `(" ", "")` fragment when
`sep == 1`; in the narrowest mode (`sep == 0`) no separator fragments are
emitted at all. Foreground colour indicates filter state:

| State    | Style                                  |
|----------|----------------------------------------|
| Enabled  | `CHANNEL_COLORS[name]` — channel color |
| Disabled | `C_LABEL_OFF` — `fg:#3a3a3a` grey      |

No background color. Each cell's mouse handler calls
`forward_toggle(channel.name)` on left `MouseEventType.MOUSE_DOWN` and
`forward_solo(channel.name)` on right `MouseEventType.MOUSE_DOWN`.

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

The list `Window` has `wrap_lines=False`. The renderer owns line wrapping via
`_entry_to_rows(entry, cols, channels, with_time)`, which is the single authority
for how an entry is laid out. `_entry_to_rows` builds the flat fragment list with
`_render_quoted_row` or `_render_action_row` (each receiving `with_time`), then
passes it through `_wrap_fragments(fragments, cols)` to produce a list of display
rows. Each row is a list of `(style, text)` fragments. `_list_text` joins rows
within an entry with `"\n"` and entries with `"\n"` before feeding the fragment
stream to the `Window`. prompt_toolkit never wraps — every `\n` in the stream is
exactly one display row.

`_row_count` delegates to `_entry_to_rows`:
```python
def _row_count(entry, cols, channels, with_time):
    return len(_entry_to_rows(entry, cols, channels, with_time))
```
This is the convergence point. Scroll math (backward-walk filling, max_offset
computation, sticky-bottom) counts rows via `_row_count`, which reaches the same
answer the renderer reaches. The two paths cannot diverge.

`with_time` is the single flag controlling timestamp visibility. It is computed
**once per render pass** as `with_time = (_scroll_offset > 0)` and passed
unchanged to every `_row_count` and `_entry_to_rows` call in that pass. Computing
it once ensures a single render never mixes timestamped and non-timestamped rows
mid-list. The max_offset walk in the scroll-up handler always uses `with_time=True`
because once any scroll has occurred every visible row carries a timestamp.

**`_wrap_fragments` algorithm** — greedy word-boundary fill:
- The fragment stream is tokenized into alternating whitespace and non-whitespace
  tokens, spanning fragment boundaries while preserving per-character style. ANSI
  SGR sequences are zero-width and attached to the preceding visible-char run.
- Each non-whitespace token is placed on the current line when it fits (with its
  preceding whitespace if the line is non-empty). When it does not fit and the
  line is non-empty, pending whitespace is dropped and a new line is started.
- **R4** — continuation rows never begin with a whitespace fragment; the pending
  whitespace before the wrapped token is always dropped on wrap.
- **Long-word fallback** — a single token wider than `cols` is hard-broken at
  exactly `cols` visible characters per row. This is the only option when no
  whitespace break point exists. Fragment styles survive the break.

`_list_text()` uses a wrap-aware bottom-up selection: given
`anchor_idx = total - 1 - _scroll_offset`, it walks backward from the anchor
accumulating wrapped display rows (via `_row_count`) until the window is filled
or index 0 is reached. The anchor entry is always included even when it alone
exceeds `list_height` — the surplus falls off the top (clip-top semantics). The
`Window` passes `get_vertical_scroll=_anchor_bottom`, which pins the rendered
content's bottom row to the window's bottom edge, so the newest included message
is always visible at the bottom, never obscured by prompt_toolkit's default
top-anchor scroll.

Row format depends on channel class (see **Display normalization** below):

- **Quoted channels (scrolled):** `HH:MM <Talker> <verb> [destination] '<message>'`
- **Quoted channels (live):** `<Talker> <verb> [destination] '<message>'`
- **Action channels (scrolled):** `HH:MM <text>` (talker-prefix color split, no verb)
- **Action channels (live):** `<text>` (talker-prefix color split, no verb)

The `HH:MM` (or `DD/MM` for entries older than 24 h) prefix is present only in the
scrolled-back view (`_scroll_offset > 0`). In the live view (`_scroll_offset == 0`)
it is suppressed, giving message text more horizontal room.

| Field       | Style                                      | Notes                                                                               |
|-------------|--------------------------------------------|-------------------------------------------------------------------------------------|
| HH:MM       | `C_TIME` — `fg:#687685`                    | From `ts`; DD/MM for entries older than 24 h; **shown only when `_scroll_offset > 0`** |
| Talker      | `C_TALKER_YOU` or `C_TALKER_OTHER`         | `C_TALKER_YOU` (soft cyan) when `talker == "you"`; `C_TALKER_OTHER` (warm tan) otherwise; `" the <descriptor>"` suffix stripped; first char capitalized |
| verb        | `CHANNEL_COLORS[channel]`                  | From `CHANNEL_VERBS` (self/other form); unknown → channel name |
| destination | `C_TALKER_YOU` or `C_TALKER_OTHER`         | `C_TALKER_YOU` when `destination == "you"`; `C_TALKER_OTHER` otherwise; `" the <descriptor>"` suffix stripped when not `"you"`; present only when non-empty |
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

**Timestamp visibility** — `_scroll_offset` also gates the `HH:MM` (or `DD/MM`)
timestamp prefix on every row. When `_scroll_offset == 0` timestamps are
suppressed (live view prioritises message bandwidth on a narrow pane). When
`_scroll_offset > 0` every visible row carries a timestamp in `C_TIME` style
(scrolled-back view is for review and benefits from time context). The flag
`with_time = (_scroll_offset > 0)` is computed once per render pass and is
uniform across all rows — a partially scrolled view never mixes timestamped and
non-timestamped rows. The very first scroll-up tick transitions from
`with_time=False` to `with_time=True`; rows that were wider without timestamps
may reflow to one extra row. This one-tick reflow is accepted.

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
`ConditionalContainer / Window`, so it is always visible below the list.
Clicking it (`MOUSE_DOWN`) resets offset to 0.

### Inactive run

When `bridge/runtime/connection.state` is absent, every text provider
(`_header_text`, `_list_text`, `_indicator_text`) returns blank fragments and
the overflow indicator is suppressed via the same `_run_active` flag. The
channel filter header blanks entirely — no cells, no separators.
Pane structure (size, splits, tmux borders, `cp -h` header status) is unchanged.
The flag is updated by the existing 250 ms poll loop on each tick.

### Colour palette

All constants are defined at the top of `bridge/panes/comm_pane.py`:

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

**Light-background shift.** On a light ("paper") terminal the **content**
colours — every `CHANNEL_COLORS` value plus `C_TALKER_YOU`, `C_TALKER_OTHER`,
`C_MESSAGE_SELF`, `C_MESSAGE_OTHER` — wash out, so each is pulled darker and
more-saturated through `pane_frame.light_shift` (gated once at load on
`pane_frame.pane_is_light("comm")` — the comm pane's OWN background, so a dark
named pane colour stays dark even on a light terminal; built in place via
`_light_content_style`). On a dark bg the shift is a no-op and the pane is
byte-for-byte unchanged. The
muted/structural colours are left untouched on purpose: `C_TIME` and
`C_LABEL_OFF` are meant to recede (the saturation floor would make them *more*
prominent), and `C_INDICATOR` is the shared cross-pane overflow amber (shifting
it here would desync the other panes' indicators on a light terminal). See
[docs/pane-frame.md](pane-frame.md) for the `light_shift` / `is_light_bg`
contract.

### Display normalization

`bridge/panes/comm_pane.py` normalizes raw GMCP payloads at render time. Raw data in
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
  - `You whisper to Dori 'hej'` (preposition inserted; `"Dori the armourer"` → `"Dori"`)
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
priority order via `_match_visible_prefix(text, prefix)`, which walks `text`
skipping ANSI SGR sequences and matches the prefix against the visible characters
(case-insensitive). This means a text that begins with ANSI-wrapped characters
(e.g. a bold-wrapped talker name) is matched correctly.

1. If the visible characters of `text` start with `"You "` (branch a): render as
   self — `"You "` in `C_TALKER_YOU`, `text[body_start:]` in `C_MESSAGE_SELF`.
   `body_start` is the byte offset returned by `_match_visible_prefix`; the body
   slice preserves any ANSI runs that follow. The `talker` field is ignored; MUME
   may set it to the character name for own socials rather than `"you"`.
2. Else if `talker` is non-empty and the visible characters of `text` start with
   `talker + " "` (branch b, case-insensitive): render as other — `matched_visible`
   (the original-cased visible chars consumed, including the trailing space) has
   `_strip_descriptor` applied after stripping the trailing space, then `" "` is
   appended, and the result is emitted in `C_TALKER_OTHER`; `text[body_start:]` in
   `C_MESSAGE_OTHER`. Covers multi-word talker names, talker/text case mismatches
   (e.g. `talker="a dwarven sergeant"`, `text="A dwarven sergeant …"`), and
   ANSI-wrapped talker names in `text`. The body slice `text[body_start:]` is taken
   from the original `text` bytes, so any embedded ANSI runs inside the message
   body keep rendering through `ANSI()` unchanged. Example:
   `talker="Vit the innkeeper"`, `text="\x1b[1mVit the innkeeper\x1b[0m bows before you."` →
   displays `"Vit "` in talker color, `"bows before you."` in message color.
3. Else (malformed — talker not at start of `text`): prepend `<Talker> ` in
   talker color (`"you"` → `"You"`), then render `text` verbatim in message
   color.

This eliminates double-talker artifacts such as `"You social You wave goodbye."` or
`"Vainamoinen emotes Vainamoinen smiles warmly."` that arise when the channel verb
is prepended to a `text` field that already embeds the talker.

Embedded ANSI in the message portion is preserved via
`prompt_toolkit.formatted_text.ANSI()`. The configured `C_MESSAGE_*` color is
applied as the default for plain (non-ANSI-styled) text.

**Talker capitalization** — `" the <descriptor>"` is stripped from the talker
before capitalization (`"Vit the innkeeper"` → `"Vit"`). Article-prefix mobs
(`"a dwarven sergeant"`, `"the gate guard"`) are unchanged — `' the '` at index 0
signals no proper name to keep. `"you"` → `"You"`.

### Dev fixture

`bridge/dev/comm.state.fixture` is a static JSON file covering all ten channels
in self and other form. Three env vars override the live paths:

| Variable           | Default                              | Purpose                         |
|--------------------|--------------------------------------|---------------------------------|
| `COMM_STATE_PATH`  | `bridge/runtime/comm.state`                  | State file the pane polls       |
| `COMM_FILTERS_CONF`| `bridge/runtime/comm_filters.conf`           | Filter persistence file         |
| `COMM_PREFS_CONF`  | `bridge/runtime/comm_prefs.conf`             | `show_header` preference file   |

Usage:

```sh
COMM_STATE_PATH=bridge/dev/comm.state.fixture \
COMM_FILTERS_CONF=/tmp/comm_filters.fixture.conf \
COMM_PREFS_CONF=/tmp/comm_prefs.fixture.conf \
python3 bridge/panes/comm_pane.py
```

Point `COMM_FILTERS_CONF` and `COMM_PREFS_CONF` at `/tmp` so toggling filters or
header visibility in fixture mode does not touch the real config. Editing either
file while the pane runs exercises the live re-read path. See
`bridge/dev/README.md` for edge cases covered by the fixture.

## Pane frame

Pane title: `comm`. The pane carries an in-pane frame (a header row plus a
half-block border) drawn by `pane_frame`, replacing the old tmux
`pane-border-status` header. Content — including the channel-filter header
described above — renders within `inner_width` / `inner_height` (`W-2` / `H-2`
when the border is on, full size when off); the frame's header label is `Comm`
(distinct from the in-content channel-filter row); the border is per-pane,
toggled by `border_comm` in `startup.conf`. See
[docs/pane-frame.md](pane-frame.md) for the frame shape, border colour, and the
`border_<key>` contract.

## Layout integration

### Pane position

Right column, top to bottom: **status → comm → ui → dev**. The comm pane sits
between `status` and `ui`. `dev` is always bottommost. When any subset of panes
is open, ordering is preserved.

### Height

`desired_comm` in `bridge/runtime/layout.conf` (default 10; content rows,
excludes title row). Cold start and WINCH size the pane from this value via
the per-pane allocation algorithm in
[ADR 0071](decisions/0071-per-pane-desired-heights.md); mid-session drag
adjusts the height freely and the new value persists as the next
`desired_comm` via `on_pane_resize.sh`. Drags on adjacent borders persist
the corresponding `desired_<pane>` keys for both neighbours. `cp -reset-heights`
restores the shipped default.

### Width

The right column has no minimum width. `ui_width` from `bridge/runtime/layout.conf`
is the sole authority (ADR 0038). The comm pane adapts to whatever width the
column provides.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -m`                           | `toggle_pane.sh comm --persist`                 |
| In-game popup → Options           | `toggle_pane.sh comm --persist`                 |
| Launcher Options → Comm pane      | `_save_conf` → `startup.conf show_comm`         |

Persistence key: `show_comm` in `bridge/runtime/startup.conf`. Fresh-install
default is `1` (comm pane on), seeded by
`bridge/launcher/templates/startup.conf` (see ADR 0101). Existing
`startup.conf` files that lack `show_comm` fall through to the aligned
`${show_comm:-1}` runtime guard in
`bridge/launcher/build_initial_layout.sh`, so upgraded installs open the
comm pane on the next cockpit start.

---
Back to [architecture.md](../architecture.md).
