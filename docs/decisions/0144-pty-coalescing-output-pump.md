# 0144 — PTY-coalescing output pump for the game pane

**Status:** Accepted
**Date:** 2026-06-20

## Context

The game pane showed an intermittent mid-burst partial frame ("flicker") on
large output bursts — `score` / `eq` in a full room, a busy combat round. It was
more pronounced through tmux and on wider panes.

`strace` confirmed the root cause: tt++ writes **one server line per `write()`**
to its controlling-terminal stdout, and because that stdout is a tty each write
is flushed immediately. A burst therefore arrives at the tmux pane as many
separate one-line writes, and the terminal/tmux is free to parse and redraw
between any two of them — so the player sees a half-painted frame for a few
milliseconds before the rest lands.

This is intrinsic to tt++'s low-latency, line-at-a-time output, not a bug or a
misconfiguration. The usual levers were each ruled out:

- **tmux** has no "hold the redraw" setting — its job is to parse the byte
  stream and redraw the pane state; it cannot know where a logical burst ends.
- **Terminal version** changes (foot, alacritty) shifted the symptom's severity
  but never removed it — the writes are genuinely separate.
- **MUME server-side** `brief` / pager settings reduce *how much* is sent, not
  *how* it is framed, and trade away information the player needs.

The boundary the terminal is missing — "these N lines are one burst" — exists
only as a timing gap in tt++'s output: lines within a burst arrive back-to-back,
then the stream goes idle. Something that watches that gap can reconstruct the
boundary the terminal cannot.

## Decision

Insert an **optional pty wrapper**, `bridge/launcher/pty_coalesce.py`, between
tt++ and the tmux pane. It spawns tt++ on a fresh pty (so tt++ still believes it
owns a tty and keeps its tty semantics and per-line flushing), then:

- **Input** (tmux pane → tt++): forwarded immediately, byte-for-byte, with zero
  buffering or delay. This is the keystroke → server hot path; it adds no
  latency.
- **Output** (tt++ → tmux pane): appended to a buffer and flushed as a **single
  `write()` per batch**. A batch closes on a sub-millisecond **read-idle
  debounce** (`MUME_COALESCE_MS`, default 1 ms) — i.e. just after the burst goes
  idle — bounded by a **size cap** (`MUME_COALESCE_CAP`, 32 KiB) and a
  **max-hold ceiling** (`MUME_COALESCE_MAX_MS`, 12 ms) measured from the oldest
  buffered byte.

The pump forwards `SIGWINCH` (re-copying winsize onto the child pty) so tt++
always renders at the correct dimensions, and forwards `SIGTERM`/`SIGHUP`/
`SIGINT` verbatim. It is stdlib-only and POSIX-only (the event loop is the
portable `selectors` module).

It is gated by `MUME_COALESCE` (default on); `MUME_COALESCE=0` is the escape
hatch that makes `wait_for_layout.sh` `exec tt++` directly, with no pump in the
path.

### Why a pty and not a pipe

A pipe would flip tt++'s stdio from line-buffered to block-buffered (stdio
buffers fully when stdout is not a tty). That would either batch unpredictably
or — worse — stall a lone line until the block buffer happens to fill. Holding a
single combat line for an arbitrary amount of time is unacceptable on a PvP
client. A pty preserves tt++'s tty line-buffering and its `isatty`/winsize
behaviour, so tt++'s output timing is unchanged; the pump alone decides batch
boundaries, and its failsafes bound the worst case.

## Relationship to ADR 0050

ADR 0050 rejected per-line *processing* on the latency-critical path — a
`RECEIVED LINE` handler routing every server line through Lua to catch a rare
event (its rejected alternative (c)): "latency cost disproportionate to the
value."

This pump is on the same path but is **categorically different**: it never
parses, splits, or rewrites byte content. It only **batches by timing**. There
is no per-line work, no dispatch, no decision that depends on what a line *says*
— bytes accumulate and flush on an idle gap. The latency it adds is the debounce
(~1 ms), negligible against network RTT and human reaction time, and the input
path adds zero.

So 0050's principle — *don't put per-line content processing on the hot path* —
is upheld, not violated. Batching-by-timing is not processing. The distinction
is the whole point: the pump buys atomic frames precisely *because* it stays
content-blind and cheap.

## Consequences

- The game pane renders each burst as one atomic frame; the mid-burst partial
  frame is gone on the tested stack.
- **The pump cannot freeze the pane.** The size cap and max-hold ceiling
  guarantee output is flushed even under a continuous, never-idle stream — there
  is no input pattern that holds bytes indefinitely.
- A new always-present process sits in the output path on every launch. It is
  small and stdlib-only, but it is one more thing that can fail; the
  `MUME_COALESCE=0` direct-exec fallback exists for exactly that.
- tt++ keeps full tty semantics (winsize, isatty, per-line flush), so nothing
  downstream of the spawn point had to change.

## Synchronized output (DEC 2026)

The pump knows each burst boundary (via the debounce), so it can additionally
bracket each batch in `ESC[?2026h` / `ESC[?2026l` — DEC 2026 synchronized
output, the "correct" atomicity primitive, which tt++ itself does not emit.

**Verified outcome:** on the tested stack (foot 1.16 / tmux 3.4), plain
`write()`-batching already renders bursts atomically, and the 2026 wrapping
produced no observable improvement. The wrapping is therefore retained behind
`MUME_COALESCE_SYNC` but **defaults off** — emitting sequences that add no value
here and could behave differently on a future terminal is the wrong default. It
is kept available as belt-and-braces for stacks that may chunk pty reads
differently (where a single batch could span multiple terminal reads and the
explicit markers would then matter).

## Alternatives considered

**(a) tmux output / redraw settings.** No lever exists: tmux's job is to parse
the stream and redraw pane state, and it has no notion of a logical burst
boundary to hold for. Rejected.

**(b) `stdbuf` forcing block buffering.** `stdbuf` can only batch by size or by
line, never by *time*. Block-buffering would stall lone lines until the buffer
fills — fatal on a PvP client. Rejected; this is the same failure mode that
rules out a pipe.

**(c) MUME server-side `brief` / pager.** Reduces the information the player
sees rather than how it is framed — the wrong trade in a PvP client where the
suppressed lines are exactly what you need. Rejected.

**(d) Patching tt++ upstream to batch its own output.** Out of scope, ties the
client to a forked tt++, and would still require tt++ to detect burst
boundaries — the same timing problem solved here, just moved into a binary we
don't want to maintain. Rejected.

## Relation to other ADRs

- **ADR 0050** — establishes the hot-path principle this ADR is measured
  against; see *Relationship to ADR 0050* above.
- **ADR 0103 / 0104** — addressed a different flicker (Windows ConPTY inbound
  burst) by moving the terminal off the ConPTY path. This ADR addresses the
  pane-internal mid-burst frame on the Linux/WSLg path and is independent of it.
