# 0090 — Profile editor clipboard: OSC 52 write, no read

**Status:** Accepted
**Date:** 2026-05-22

## Context

Phase C of the profile-editor rework wired copy / cut / paste into the
Editor-mode text buffer and the Lite Pattern / Body text fields. The
in-app side is uncontroversial — every text surface needs a
selection-aware register, and a single shared `_editor_clipboard`
covers all three. The interesting question is the system clipboard:
should `c-c`/`c-x` write to it, and should `c-v` read from it?

The launcher is a pre-tmux full-screen surface running under
prompt_toolkit. It does not have direct access to the system clipboard
the way a desktop application does — its only handle on the
clipboard lives in the terminal emulator that hosts it. Two terminal
mechanisms can bridge the gap:

- **OSC 52** (`ESC ] 52 ; c ; <base64> BEL`) — out-of-band sequence the
  application writes to its output stream. The terminal decodes it and
  pushes the payload onto the system clipboard. Supported by every
  modern terminal that matters (iTerm2, kitty, Alacritty, WezTerm,
  recent VTE-based terminals, recent xterm) — sometimes
  off-by-default for the read variant, on-by-default for the write
  variant. Terminals that don't support it silently discard the
  sequence.
- **Bracketed paste** — the terminal wraps a system-clipboard paste in
  `ESC [ 200 ~ ... ESC [ 201 ~`. Inbound only. Triggered by the
  user's *terminal-native* paste shortcut (`Cmd-V` on macOS,
  `Ctrl-Shift-V` / right-click on Linux, etc.), not by `c-v` inside
  the application.

We considered three combinations for the launcher's clipboard.

## Options considered

### Option A — OSC 52 write, OSC 52 read (rejected)

Both directions on the wire. `c-c`/`c-x` emit a write sequence; `c-v`
emits a read sequence (`ESC ] 52 ; c ; ? BEL`), then blocks reading
from stdin until the terminal replies with the base64-encoded
clipboard contents.

Cons:

- **Read is off by default in most terminals.** xterm requires
  `allowWindowOps`; iTerm2 ships with it gated behind a permission
  prompt; VTE-based terminals (GNOME, Tilix) disable it entirely. So
  for the majority of users the read path silently fails.
- **Read needs a stdin round-trip.** prompt_toolkit owns the input
  pipe. Stealing it for a synchronous read is fragile: it requires
  pausing the input loop, draining the terminal's response into a
  parser that is *not* the prompt_toolkit key parser, and resuming.
  Easy to get wrong; hard to test.
- **Read is redundant.** The same paste that an OSC 52 read would
  fetch is already available via the terminal's bracketed-paste
  shortcut, with no escape-sequence dance and no permission prompt.

### Option B — OSC 52 write only (chosen)

`c-c`/`c-x` always emit a write. `c-v` reads from the in-app register
only. Pasting from another application uses the terminal's own paste
shortcut, which arrives as bracketed paste — wired up in Editor mode
and in both Lite text fields.

Asymmetry: `c-v` does *not* read the system clipboard. Two flows
exist for inbound text, and the user picks based on source:

- **Launcher → launcher:** `c-c` in one editor field, `c-v` in
  another. The in-app register covers this end-to-end. OSC 52 just
  rides along so the same text is also available outside the
  launcher.
- **Outside → launcher:** the terminal's paste shortcut. Bracketed
  paste handlers normalise CRLF / lone CR to `\n`, flatten newlines
  to spaces in Pattern (single-line field), and insert as-is in Body
  and Editor mode.

### Option C — no system clipboard at all (rejected)

In-app register only; copy and cut never touch OSC 52. Pros: trivial
to implement; no escape-sequence handling at all.

Cons: the most common flow — copy a snippet from a profile, paste it
into a chat client or a forum post — silently breaks. The escape
sequence costs nothing in the no-support case (terminals discard
unknown OSCs), so the asymmetry of "in-app works, system clipboard
doesn't" has no upside.

## Decision

Adopt Option B: **OSC 52 write yes, OSC 52 read no.**

The implementation is `_emit_osc52_copy(text)` — base64-encode the
UTF-8 text, build the OSC 52 sequence, write through
`_app.output.write_raw()` (the prompt_toolkit output owns the
screen), and flush. Errors are swallowed: a key handler must never
raise on a courtesy operation. No tmux passthrough wrapping is
needed — the launcher runs *before* tmux attaches, so its OSC
sequences travel directly to the outer terminal.

`c-v`'s deliberate-asymmetry — it reads from the in-app register
only — is documented in `docs/launcher.md` next to the keymap so
users don't expect it to mirror desktop-application semantics.

## Consequences

- Copy and cut in any of the three text contexts place the selection
  (or the current line on a no-selection copy/cut) on the system
  clipboard on terminals that implement OSC 52 write. On terminals
  that don't, nothing breaks: the in-app register still works.
- Inbound text from another application uses the terminal's own paste
  shortcut. The launcher's bracketed-paste handlers normalise line
  endings and dispatch to whichever text field has focus.
- `c-c` no longer quits the launcher from inside the profile editor.
  It still quits from every other frame. ESC remains the documented
  way to exit the editor (saving any pending edits via the existing
  `_profile_editor_save_and_close` path).
- If a future terminal generation makes OSC 52 read universally
  available and on-by-default, revisiting this decision is cheap:
  the in-app register stays; only the `c-v` handler changes. The
  bracketed-paste handler is independent.
