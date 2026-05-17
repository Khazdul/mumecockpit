# 0081 — `#format` code escaping in alias and event bodies

**Status:** Accepted
**Date:** 2026-05-17

## Context

`#format` accepts both *format codes* (`%U`, `%T`, `%t`, `%p`,
`%.Ns`, …) that read from the format engine itself, and *alias arg
substitutions* (`%0..%99`) that read from the surrounding alias or
event body. Inside an alias or event body the rule for substitutions
is well-documented in `ttpp_manual.txt`: write `%%N` if you want the
literal substitution `%N` to survive one level of body unwrapping
and reach `#format` at fire time.

What is *not* documented is what happens when the same `%%X` pattern
is used for a format code: e.g. `#format _ts {%%U}` inside an alias
body. The intent is "have the alias body unwrap `%%U` to `%U` so
`#format` sees a format code at fire time."

Empirically, the platforms disagree:

| Platform | tt++ build | Behaviour of `%%U` / `%%.1s` in alias body |
|----------|------------|---------------------------------------------|
| Ubuntu (source-built) | 2.02.61 | Unwraps to `%U` / `%.1s`; format code fires correctly. |
| macOS (Homebrew) | 2.02.61 | Does **not** unwrap; `#format` receives literal `%U` / `%.1s` and the destination variable ends up as that literal string. |

Only `%%0..%%99` (alias args) are reliably unwrapped on both
platforms. The two builds are the same upstream version number;
the asymmetry appears to be a build/distribution difference and is
not called out in the manual.

The bug that surfaced this was the macOS-only connect-time deadlock
originally attributed to `\xFF` not evaluating inside `#if` string
literals. The actual cause was `#format _first {%%.1s} {%%0}` inside
`_register_run_log_capture` leaving `_first` as the literal text
`%.1s` on macOS instead of the first byte of `%0`. The IAC filter in
the `SENT OUTPUT` handler therefore always passed, the connect-time
IAC burst flowed through `#lua {USER_INPUT:...}` for every
subnegotiation, and the macOS PTY (~4 KB) overflowed between tt++
and the `lua` `#run` session. See
[ADR 0076](0076-run-log-iac-filter.md) for the full incident.

## Decision

In alias and event bodies that contain `#format` (or any other
command consuming `%`-codes at fire time), follow this convention:

- **Single `%` for format codes** — `%U`, `%T`, `%t`, `%p`, `%.Ns`,
  any other engine-side code. These reach `#format` as themselves
  and are interpreted at fire time on both platforms.
- **Double `%%` only for alias arg substitutions** — `%%0..%%99`.
  These are the substitutions documented in `ttpp_manual.txt` and
  the only `%%` forms that unwrap reliably on Ubuntu and macOS
  alike.

Worked example, after the fix
in [`ttpp/core/run_log.tin`](../../ttpp/core/run_log.tin):

```tintin
#%1 #event {SENT OUTPUT} {
    #class {core} {open};
    #format _first {%.1s} {%%0};    /* single % for the format code, %% for the arg */
    #class {core} {close};
    #if {"$_first" != "$_iac"} {
        #if {&_run_log_path} {
            #class {core} {open};
            #format _ts {%U};        /* single % */
            #format _sent {%p} {%%0}; /* single % for %p, %% for %0 */
            #class {core} {close};
            #line log $_run_log_path {$_ts > $_sent}
        };
        #if {"%%0" != ""} {#lua {USER_INPUT:%%0}}
    }
};
```

## Consequences

- **Cross-platform parity.** `#format` codes evaluate the same way
  on macOS Homebrew tt++ 2.02.61 and Ubuntu source-built tt++
  2.02.61. There is no longer a class of bug that hides on Linux
  and only manifests in the macOS PTY.
- **One rule for two cases.** The convention is simple to apply
  mechanically: if it's `%%N` for a digit `N`, leave it; otherwise
  collapse `%%X` to `%X`.
- **Manual is not authoritative here.** `ttpp_manual.txt` documents
  alias arg substitution but does not address `%%`-format-code
  unwrapping in alias bodies. This ADR records the empirical
  finding so the next reader does not have to rediscover it.
- **One audit done.** A grep of `ttpp/` for `%%[A-Za-z]` returns no
  matches at the time of this ADR; the only remaining `%%` forms
  are `%%0..%%99` (alias args) or `%%%N` / `%%%%N` nested-arg forms
  in `ttpp/core/mud_events.tin`. New `#format` callers must follow
  the rule.

## Alternatives considered

**(a) Use `%%X` everywhere and rely on the per-platform unwrap.**
Rejected — that is the pattern that broke macOS in
[ADR 0076](0076-run-log-iac-filter.md). The unwrap of `%%X` for `X`
outside `0..99` is undocumented and observably platform-dependent
on a same-version build.

**(b) Wrap `#format` calls in a helper function.** Rejected —
function indirection in tt++ reuses the same `%U` evaluation across
all events in a tight batch (already documented in
[docs/runs.md](../runs.md#per-run-text-log-log) and the run-log
header comments), so a single helper would break per-line timestamp
resolution for the run-log capture, which was the original reason
to inline `#format _ts {%U}`. The convention here is the cheaper
fix.

**(c) Pin tt++ to a specific build that unwraps `%%X` for all `X`.**
Rejected — platform support is split Tier 1 / Tier 2 (per
[ADR 0020](0020-platform-support-policy.md)) and a build pin would
require us to vendor or block the Homebrew tt++ formula. Following
the documented `%%0..%%99` rule and using single `%` for format
codes is portable across both Tiers without intervention.

## Relation to other ADRs

- **Resolves the macOS symptom in [ADR 0076](0076-run-log-iac-filter.md)** —
  the run-log IAC filter's connect-time deadlock on macOS, originally
  attributed to `\xFF` evaluation in `#if` conditions, was actually
  caused by `%%.1s` not unwrapping. ADR 0076 has been amended with a
  corrected-diagnosis section that points back here.
- **Complements [ADR 0020](0020-platform-support-policy.md)** — adds
  one more concrete tt++-side gotcha to the macOS Tier-2 list,
  alongside the existing `stty`-over-`tput` precedent
  ([ADR 0021](0021-stty-over-tput-for-terminal-dimensions.md)).
