# ADR 0048 — ttpp/profiles/ path rename

**Status:** Accepted  
**Date:** 2026-05-08

## Context

ADR 0044 established a clean vocabulary split: "profile" refers to the settings
file that gets loaded for a play session; "session" is reserved for tt++'s own
concept (the named connection opened via `#ses`). The class name and the tt++
session name both equal the profile name — that is intentional and unchanged.

However, the on-disk directory path (`ttpp/sessions/`) continued to use
"sessions", creating a naming collision at the filesystem level: `ttpp/sessions/`
at the path level looks like the tt++ sessions directory, not the profile-storage
directory. This made the vocabulary rule harder to teach and the directory listing
ambiguous.

## Decision

Rename `ttpp/sessions/` to `ttpp/profiles/`.

Only the directory name and the string literals that reference it change. The
class name, the tt++ session name, and all variable names remain equal to the
profile name — the identity is unchanged.

## Migration

A one-shot migration block is placed in both `bridge/launcher/launcher.sh` and
`bridge/launcher/tmux_start.sh`, after the existing ADR 0047 runtime-
consolidation block:

```bash
# ttpp/sessions/ → ttpp/profiles/ (ADR 0048)
if [ -d ttpp/sessions ] && [ ! -d ttpp/profiles ]; then
    mv ttpp/sessions ttpp/profiles
fi
```

The migration is idempotent: skipped when `ttpp/profiles/` already exists. It
must appear in both launchers because after a self-update the user may re-exec
`launcher.sh` directly without going through `start.sh`.

## Rationale

- **Vocabulary consistency.** "profile" means the settings file; "session" is
  the tt++ concept. The directory name now matches the vocabulary rule from
  ADR 0044 without exception.
- **Reduced ambiguity.** `ls ttpp/` now unambiguously shows a `profiles/`
  directory rather than a `sessions/` directory that collides with the runtime
  concept.
- **Zero functional change.** Only path strings are updated; behaviour,
  class names, and session names are identical.

## References

- ADR 0044 — Runs and character-scoped persistence (defines the profile/session
  vocabulary split that this ADR enforces at the filesystem level)
- ADR 0047 — bridge/runtime/ consolidation (parallel migration pattern)
