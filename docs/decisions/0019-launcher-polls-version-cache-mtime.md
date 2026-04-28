# ADR 0019 — Launcher polls version.cache mtime to detect update availability

Date: 2026-04-28
Status: Accepted

## Context

The launcher (`bridge/launcher.sh`) displays an "Update available" row when
`_update_available()` returns true. That function reads `bridge/version.cache`
and compares `latest=` against the installed VERSION.

`version_check.sh` is launched in the background by the launcher on cold start.
It performs a `curl` against the GitHub releases API, which takes roughly 3 s
on a normal connection. The launcher built its `_ITEMS` array **once**, at
script start, before calling the read-key loop. Because the cache did not yet
exist when `_ITEMS` was built, `_update_available()` returned false and the
Update row was omitted.

The result: on every cold start the launcher showed no Update row even when a
newer release was available. The user had to dismiss the launcher and relaunch
for the row to appear. Reproduced consistently in the test distro during
v0.2.5/v0.2.6 validation.

## Decision

Extract `_ITEMS` construction into a `_build_menu_items()` function. In the
main read-key loop, poll `version.cache`'s mtime at approximately 200 ms
cadence (the existing `read -t 0.2` timeout already provides this). On each
timeout tick, compare the cached mtime against the last-seen mtime. When the
mtime changes, call `_build_menu_items()` again, preserve `_SEL` by item name,
and set `_DIRTY=1` to trigger a redraw on the next iteration.

    _CACHE_MTIME=""
    while true; do
        # ... handle key input ...
        # on read timeout:
        _m=$(stat -c %Y bridge/version.cache 2>/dev/null)
        if [[ "$_m" != "$_CACHE_MTIME" ]]; then
            _CACHE_MTIME=$_m
            _build_menu_items
            _DIRTY=1
        fi
    done

No additional processes are spawned. The stat call is local and sub-millisecond.

## Consequences

- The Update row appears within ~200 ms of `version_check.sh` writing the
  cache. The user never needs to relaunch.
- The poll adds one `stat` call per 200 ms loop iteration — imperceptible
  overhead on any hardware that can run the launcher.
- The launcher's non-blocking-on-network design is preserved: startup is not
  delayed waiting for the cache. The launcher simply reacts when the cache
  materialises.
- If `version.cache` does not exist (first-ever cold start, no network), the
  stat returns empty; `_CACHE_MTIME` stays empty; no rebuild is triggered until
  the file appears.

## Rejected alternatives

**inotifywait.** Would eliminate the polling interval entirely and fire
immediately on cache write. Rejected: `inotifywait` (`inotify-tools`) is not
installed by default on all target distros, would add an external package
dependency, and requires a background subshell. The 200 ms poll achieves the
same user-visible result without any of this.

**Block at startup until cache exists.** A `while [[ ! -f bridge/version.cache ]]; do sleep 0.2; done` before entering the read-key loop would guarantee the Update row is present from frame one. Rejected: violates the non-blocking design documented in `docs/bridge-services.md`. The launcher must be immediately responsive even when the network is slow or unavailable.

## Out of scope

- Polling for changes to `VERSION` or other files during a launcher session.
- Debouncing multiple rapid mtime changes (in practice version_check.sh writes
  the cache once per invocation).
