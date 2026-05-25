# Burst-latency benchmark harness

Standalone dev tool for measuring how long tt++ takes to process a tight
burst of inbound server lines. Not shipped, not auto-loaded — files
under `tools/bench/` are invoked manually.

The goal is to attribute visible rendering lag between:

- the run-log `RECEIVED LINE` handler (per-line `#format %U` plus
  `#line log` write to `_run_log_path`),
- the project's action set (matching plus `#lua {events.emit(...)}`
  dispatch),
- and baseline tt++ overhead (regex match of inactive actions).

## Pieces

- `burst_server.py` — TCP server. On every line equal to `benchgo` from
  the connected client, emits `BENCH_START`, N fixture lines, `BENCH_END`
  (CRLF-terminated). With `--delay-ms 0` the entire burst goes in a
  single `sendall()`.
- `fixtures/neutral.txt` — ~20 lines matching no `#action` in the
  project. Measures pure regex-match + `RECEIVED LINE` cost.
- `fixtures/combat.txt` — ~20 lines matching `#action` patterns from
  `ttpp/core/mud_events.tin`. Measures action-body cost (the
  `#lua {events.emit(...)}` pipe dispatch).
- `bench.tin` — tt++ harness in a dedicated `{bench}` class. Stamps
  microsecond timestamps on `BENCH_START` / `BENCH_END` and prints a
  single `BENCH RESULT: <us> us` line per burst. Cleanup: `bench_off`.

## Prerequisite: point the cockpit at the bench server

The cockpit's game session must be connected to the bench server
(`localhost:4243`) instead of MUME. The launcher already supports this
via `bridge/runtime/startup.conf` — set:

```
connection_mode=custom
connection_host=localhost
connection_port=4243
```

(Or use the launcher's "Custom host/port" connection settings; it
writes the same keys.) `connection_mode=custom` skips the default
`mmapper`/`direct` paths and connects with plain `#ses` to the host and
port given. Restore the value when done.

The cockpit will treat the bench server as the MUD. Ignore any
login-screen UI state, missing GMCP modules, or "no character" UI
artifacts — those have no bearing on the measurement, which is purely
about per-line processing inside tt++.

## Procedure

1. Start the server in another terminal:

   ```
   python3 tools/bench/burst_server.py --fixture tools/bench/fixtures/neutral.txt --lines 10
   ```

2. Launch the cockpit (`./start.sh` etc.) with `startup.conf` pointed
   at `localhost:4243` as above. Wait for the game session to attach to
   the bench server.

3. In the game-input pane, load the harness:

   ```
   #read tools/bench/bench.tin
   ```

4. Wait a couple of seconds. Action registration inside the cockpit is
   asynchronous (Lua-driven on `SESSION CONNECTED`), so the full action
   set may not be installed for ~1–2 s after the session attaches.

5. Type `benchgo` (just the word, sent as a normal command). The server
   emits one burst; the harness prints exactly one line:

   ```
   BENCH RESULT: <microseconds> us
   ```

6. Repeat `benchgo` for more samples. Take the median across, say, 5–10
   bursts at each setting — TCP scheduling jitter on the loopback is
   real and you want the central tendency, not the worst draw.

7. When done: `bench_off` removes the `{bench}` class. Re-`#read
   tools/bench/bench.tin` to bring it back. Restore `startup.conf` to
   its real connection settings.

## Toggle matrix

Run each cell with both fixtures and burst sizes 10 / 50 / 100. Restart
`burst_server.py` between fixture/size changes (it loads the burst
contents at startup).

| Cell | Setup | Exact commands |
|------|-------|----------------|
| **A** | Full cockpit, run-log armed | `#var {_run_log_path} {tools/bench/bench.log}` |
| **B** | Full cockpit, run-log disarmed | `#unvar _run_log_path` |
| **C** | As B, plus all cockpit events off | `#unvar _run_log_path`; `#unevent {RECEIVED LINE}`; `#unevent {SENT OUTPUT}`; `#unevent {RECEIVED INPUT}` |
| **D** | Bare tt++ (no cockpit, no brain) + `#read tools/bench/bench.tin` | (run `tt++` directly, `#session bench localhost 4243`, then `#read tools/bench/bench.tin`) |

Subtractions:

- **A − B** ≈ run-log cost (per-line `#format %U` + `#line log` write).
- **B − C** ≈ non-run-log event cost (the other registered `RECEIVED
  LINE` / `SENT OUTPUT` / `RECEIVED INPUT` handlers).
- **C − D** ≈ the cockpit's action-set match cost (every action is
  still installed; their bodies just don't fire because the fixture
  lines either don't match — neutral — or only dispatch into a
  brain-less session — combat).

## Reading the numbers

Per-line costs show up as the **slope** across burst sizes 10 / 50 /
100; fixed overhead shows up as the **intercept**. The interesting
comparison is slopes between cells, not headline totals — a 2× ratio in
totals at N=10 may collapse at N=100 if it was mostly fixed setup.

Plot the medians as `delta(us)` vs N for each cell × fixture and fit a
line. A clean per-line cost report is the difference in slopes between
two cells, not a single ratio.

## Notes

- `--delay-ms 0` is the headline configuration: one TCP segment, worst
  case for tt++'s read-buffer drain. Non-zero `--delay-ms` is for sanity
  checks (e.g. confirming the harness scales linearly with N).
- `BENCH_START` / `BENCH_END` are chosen to match no `#action` in the
  project. If a future action ever consumes one of them, rename the
  markers in both `burst_server.py` and `bench.tin` together.
- The bench server keeps a single client connection at a time and loops
  on disconnect; Ctrl-C cleanly exits.
