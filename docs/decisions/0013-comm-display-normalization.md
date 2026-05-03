# 0013 — Comm display normalization in the renderer

**Status:** Accepted
**Date:** 2026-04-26

## Context

`Comm.Channel.Text` payloads vary significantly per channel. For non-self
messages, the raw `text` field repeats the talker's name and verb as a prefix
(e.g. `"Besor narrates 'message'"`, `"Vainamoinen waves goodbye."`), and
quoted-channel messages include channel-specific suffixes such as
`" in Khuzdul."`. The MUME server controls this format; it is not normalized
before storage.

Prior to this decision, `comm_pane.py` passed `text` verbatim through
`prompt_toolkit.ANSI()`. This produced a doubled talker prefix on screen
(`Besor narrates Besor narrates 'message'`) and showed language suffixes that
clutter the display. The `caption`-lowercased verb was used for all messages
without a self/other distinction, and talker coloring was driven by
`talker_type` (`ally`/`enemy`/`neutral`/`npc`).

## Decision

Normalize at the renderer (`bridge/comm_pane.py`). Raw data in Lua
(`state.comm.history`), `bridge/comm.state`, and `logs/comm_archive/<profile>.jsonl`
is preserved verbatim.

The renderer carries three lookup tables:

- **`CHANNEL_VERBS`** — self/other verb forms per channel, replacing
  `caption`-lowercased verbs and providing a `talker == "you"` variant.
- **`CHANNEL_LABELS`** — hardcoded 2–3 char header abbreviations, replacing the
  dynamic label-collision algorithm. The `label` field in `comm.state` is
  ignored by the renderer (kept for backward compatibility).
- **`CHANNEL_COLORS`** — per-channel truecolor foreground for verb and header label.

Message extraction is keyed off channel type:

- **Quoted channels** (`tales`, `tells`, `says`, `yells`, `whispers`, `prayers`,
  `songs`, `questions`): extract the substring between the first and last `'` in
  `text`. Wrap in `'…'` for display. Self messages (`talker == "you"`) carry
  only the bare text — wrap directly.
- **Action channels** (`emotes`, `socials`): strip a leading `<talker> ` or
  `You ` prefix. Display without quotes.

Talker color is now self vs other (`C_TALKER_SELF` / `C_TALKER_OTHER`) rather
than `talker_type`. Message color is similarly split (`C_MESSAGE_SELF` /
`C_MESSAGE_OTHER`). Talker-type styling is removed — no consumer was using it
visually beyond the color distinction.

## Consequences

- **Archive stays canonical and re-renderable.** Raw GMCP `text` is preserved
  in `comm.state` and the JSONL archive. Future render changes can reprocess
  historical data without loss.
- **Renderer carries small per-channel knowledge.** `CHANNEL_VERBS`,
  `CHANNEL_LABELS`, and `CHANNEL_COLORS` must be updated if MUME adds channels
  or changes message format. Unknown channels fall back gracefully (channel name
  as verb, `channel[:2].capitalize()` as label, neutral grey as color).
- **Talker-type styling is removed.** `talker_type` values in history entries
  (`ally`/`enemy`/`neutral`/`npc`) are no longer used for color. The field
  remains in the schema for potential future use.
- **Header labels are now stable.** Labels no longer depend on `Comm.Channel.List`
  order, so they survive server-side channel reordering.

## Alternatives considered

**Normalize in `comm_log.lua`.** Rejected — would pollute `state.comm.history`,
`comm.state`, and the JSONL archive with renderer assumptions. The archive must
remain a faithful record of what was received from the server.

**Pass through verbatim (status quo).** Rejected — doubled talker prefix and
inconsistent verb forms are visible UX problems; language suffixes clutter quiet
messages.

**Normalize in `comm_store.lua` at archive-write time.** Rejected — same
objection as normalizing in `comm_log.lua`; the archive loses its round-trip
fidelity.

---

## 2026-04-26 update — Action channels use text-verbatim rendering

**Problem:** The original decision described action channels (`emotes`, `socials`)
as stripping a leading `<talker> ` or `You ` prefix from `text`, then rendering
the remainder with the standard `<time> <Talker> <verb> <message>` layout. In
practice this produced doubled talker artifacts:

- `"Vainamoinen emotes Vainamoinen smiles warmly."` — talker appears twice when
  `text` already begins with the talker name.
- `"You social You wave goodbye."` — same doubling for self socials.

The root cause: MUME's GMCP `Comm.Channel.Text` for `emotes` and `socials` embeds
the full `<talker> <verb-phrase>` in `text` (e.g. `"Vit the innkeeper bows
respectfully."`). There is no clean way to strip just the verb without also
consuming part of the talker's embedded name in edge cases.

**Change:** Action channels now use text-verbatim rendering (`_render_action_row`):

```
HH:MM <text>
```

No channel verb is prepended. No standalone talker fragment is emitted. Instead,
`text` is rendered verbatim with a talker-prefix color split:

- `talker == "you"` and `text` starts with `"You "` → `"You "` in
  `C_TALKER_SELF`, rest in `C_MESSAGE_SELF`.
- `text` starts with `talker + " "` (exact prefix, including multi-word names) →
  prefix in `C_TALKER_OTHER`, rest in `C_MESSAGE_OTHER`.
- Malformed (talker not at start of `text`) → prepend `<Talker> ` in talker
  color, then `text` verbatim in message color.

**Why:** GMCP for emotes and socials embeds the talker and verb inside `text`;
reconstructing the layout client-side produced doubled talkers. Text-verbatim
rendering is faithful to the server's intended output while still applying the
self/other color split.

**Not changed:** Quoted channels (`tales`, `tells`, `says`, `yells`, `whispers`,
`prayers`, `songs`, `questions`) retain the original verb+extraction layout, now
extended to also render an optional `destination` field between verb and message.

---

## 2026-04-28 update — Destination fallback and case-insensitive action detection

**Problem:** Two further GMCP inconsistencies observed in live traces:

1. Incoming tells and whispers omit `destination`. MUME embeds `"tells you"` in
   `text` but sends no `destination` field. The renderer was displaying
   `"Gibur tells 'np :)'"` — missing the `"you"` destination entirely.

2. Own socials arrive with `talker` set to the character name (e.g. `"Globur"`)
   rather than `"you"`, while `text` starts with `"You "`. The `talker == "you"`
   guard in the old self-detection branch never fired, so the renderer fell
   through to the "other" branch and produced `"Globur You tip your helmet."`.

3. Mob socials have `talker` in lowercase (e.g. `"a dwarven sergeant"`) while
   `text` capitalizes the first word (`"A dwarven sergeant bows for you."`). The
   case-sensitive `text.startswith(talker + " ")` match failed, triggering the
   fallback prepend and producing doubled talker output.

**Changes:**

- **`DIRECTED_CHANNELS`** — new module-level set `{"tells", "whispers"}`. In
  `_render_quoted_row`, after reading `destination`: if `destination` is absent
  and `channel in DIRECTED_CHANNELS` and `talker != "you"`, fill
  `destination = "you"`. Applied only to incoming directed channels; `says`,
  `yells`, `tales`, `prayers`, `songs`, `questions` are unaffected.

- **`DESTINATION_PREPOSITIONS`** — new module-level dict `{"whispers": "to"}`.
  In `_render_quoted_row`, when `destination` is set, a preposition fragment is
  inserted in `verb_style` between the verb and destination fragments for channels
  that have a table entry. Whispers becomes `"whisper to <dest>"`. Channels with
  no entry (tells, questions, etc.) take the destination as a direct object and
  are unaffected.

- **`_render_action_row` self-detection** — priority now driven by `text` prefix,
  not by `talker`. Branch a: `text.startswith("You ")` → self render (ignores
  `talker`). Branch b: case-insensitive `text.lower().startswith(talker.lower() + " ")`
  → other render, with `text`'s original casing used for the displayed prefix.
  Branch c (fallback) unchanged.

**Rationale:** GMCP inconsistency originates on the MUME server and is not
predictably fixable at the Lua layer without mutating stored history. Normalizing
in the renderer keeps raw data pristine while correcting display artifacts at the
only place that owns the view.

---

## 2026-05-04 update — Strip `" the <descriptor>"` suffix from NPC names

**Problem:** MUME mob names include a descriptor suffix
(`"Vit the innkeeper"`, `"Takhr the orkish warden"`, `"Gibur the gate guard"`).
These suffixes clutter displayed names: `"Vit the innkeeper narrates '...'"` vs
the intended `"Vit narrates '...'"`. The descriptor is purely a MUME world-flavor
annotation; the proper name alone is sufficient for identification in the pane.

**Change:** A new module-level helper `_strip_descriptor(name)` is added to
`bridge/comm_pane.py`. It finds the first occurrence of `' the '` (with a leading
space) in `name`. If the match is at index > 0, it returns `name[:idx]`; otherwise
it returns `name` unchanged.

The helper is applied at render time in three places:

- **`_render_quoted_row` — talker:** `_strip_descriptor(talker)` before
  uppercasing the first character. The `"you"` branch is unaffected.
- **`_render_quoted_row` — destination:** `_strip_descriptor(destination)` before
  uppercasing the first character. The `destination == "you"` branch is unaffected.
- **`_render_action_row` — branch b (talker prefix in `text`):** `prefix_len` is
  computed from the original `talker` length so the correct slice of `text` is
  consumed. `display_prefix` is derived by calling `_strip_descriptor` on
  `text[:len(talker)]` (original casing from `text`) and appending a single space.
  Branch c (fallback) also applies `_strip_descriptor` before uppercasing.

**Article-prefix mob exclusion:** Names that start with `"the "` (e.g.
`"the gate guard"`) contain `' the '` at index 0, which the helper treats as
"no proper name to keep" and returns unchanged. Names like `"a dwarven sergeant"`
contain no `' the '` at all and are also unchanged. This ensures article-prefix
mobs are never partially stripped.

**Why the renderer, not Lua:** Raw data in `state.comm.history`, `bridge/comm.state`,
and the per-profile JSONL archive must remain a faithful record of what the server
sent. Stripping at any earlier stage would lose the original name, breaking
re-renderability and diff-ability of archive entries. The renderer is the only
place that owns the view; it is the correct and only place for this normalization.

---

## 2026-05-04 update — Timestamp visibility tied to scroll state

**Rule:** When `_scroll_offset == 0` (live view), the `HH:MM` / `DD/MM` timestamp
prefix is suppressed on every row. When `_scroll_offset > 0` (scrolled-back view),
every visible row carries the timestamp in `C_TIME` style.

**Why here:** The comm pane is typically narrow (25–40 columns). In the live view
the user is watching new messages arrive in real time and does not need per-message
time context — the session is happening now. Suppressing the timestamp frees 6
characters of horizontal space, allowing longer messages to fit on fewer rows (e.g.
a 29-column pane gains about one extra word per line). The scrolled-back view is
used for review — the user is reading history and wants to know when each message
was sent. Showing the timestamp there is the right trade-off.

**Why `_scroll_offset` is the gate:** `_scroll_offset == 0` is already the
authoritative signal for "live view". Deriving `with_time` directly from it keeps
the coupling explicit and avoids a separate flag that could drift out of sync.

**Why uniform per render pass:** `with_time = (_scroll_offset > 0)` is computed
once in `_list_text` and once in the max_offset walk, then passed unchanged to
every `_row_count` and `_entry_to_rows` call in that pass. This guarantees that
layout measurement and rendering always agree on whether a row carries a timestamp.
A per-entry decision (e.g. based on timestamp age relative to the view cutoff)
would let layout and render diverge for entries near the top or bottom of the
visible window, producing clipping or blank rows.

**Accepted one-tick reflow:** The very first scroll-up tick transitions
`with_time` from `False` to `True`. Rows that were wider without a timestamp now
carry a 6-character prefix and may reflow to one extra line. This is a single
visual jump on the first wheel tick. Compensating for it would require measuring
both layouts simultaneously or delaying the toggle, which adds complexity for
marginal benefit. The reflow is accepted.

**`with_time` threads through `_entry_to_rows` and `_row_count`:** Both functions
accept `with_time` as an explicit parameter and forward it to the render helpers
(`_render_quoted_row`, `_render_action_row`). This is the convergence point
established by the renderer-owns-wrapping ADR (see decisions directory): every
callsite that measures row counts uses the exact same layout that the renderer
will produce for those same entries. There is no separate measurement path.
