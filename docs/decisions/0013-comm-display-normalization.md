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
