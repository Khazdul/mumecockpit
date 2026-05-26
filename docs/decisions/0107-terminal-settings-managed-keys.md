# 0107 — Terminal Settings: managed-keys foot.ini editing and user-selectable window mode

Status: Accepted. Supersedes parts of ADR 0104.

## Context

ADR 0104 established the foot/WSLg Windows deployment and made two
deliberate calls that no longer hold: it forced `initial-window-mode=
fullscreen`, and it scoped the launcher's foot.ini writer to a single
surgical `font=` line rewrite.

The Terminal Settings page is now expanding to expose padding, background,
transparency (`alpha`), cursor style and blink, and — reversing the
fullscreen-only call — user-selectable window mode with windowed-mode pixel
dimensions.

## Decision

1. Window mode becomes user-selectable (windowed / maximized / fullscreen);
   the shipped default stays `fullscreen`. The original fullscreen-only
   rationale — one predictable layout — is outweighed now that switching is
   a one-tap launcher affordance.

2. The foot.ini writer becomes a managed-keys read/modify/write over a fixed
   set of (section, key) pairs across the implicit leading section,
   `[colors]`, and `[cursor]`. For each managed key: rewrite the line in
   place if present; append it to the section if the key is absent; append
   the section header then the line if the section is absent. All
   non-managed lines — comments, formatting, unmanaged keys — are preserved
   untouched, and the write stays atomic. This keeps ADR 0104's core intent,
   never clobbering the user's file, while lifting the single-line limit.

3. The shipped `install/examples/foot.ini` template carries every managed
   key explicitly, so on a clean install the writer's path is always a pure
   in-place rewrite; section/key insertion exists only as a robustness
   fallback for hand-edited files.

4. Windowed-mode initial dimensions default to a resolution-derived size
   (~60% width, ~80% height of the primary monitor), computed at install
   time by the Windows installer — PowerShell, which can read the monitor
   directly — and seeded into `initial-window-size-pixels`. In-WSL
   resolution detection is rejected: under WSLg's Wayland/RAIL there is no
   reliable single-screen query.

## Consequences

- The launcher can edit the full managed set without risk to the rest of
  foot.ini.
- An upgraded install whose foot.ini predates a managed key gets that key
  materialised at its default on the first Apply — benign.
- `initial-window-mode`'s "initial" semantics are acceptable: the supervisor
  relaunches foot on every Apply, so the mode applies fresh each time.
- Transparency is exposed despite uncertainty over whether WSLg composites
  `alpha`; the default of 1.0 is a no-op, so a non-compositing host degrades
  to harmless.

## Supersedes

The fullscreen-only decision and the single-`font=`-line writer scope from
ADR 0104. ADR 0104 otherwise stands.
