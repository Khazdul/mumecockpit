#!/usr/bin/env bash
# bridge/ping_monitor.sh — session-scoped background ping monitor.
# Spawned by tmux_start.sh and launcher.sh; self-terminates when tmux:mume dies.
# Single-instance guard via bridge/.ping_pid. Writes bridge/ping.cache atomically.

set -u

cd "$(dirname "$0")/.."

_PID_FILE="bridge/.ping_pid"
_CACHE="bridge/ping.cache"
_TMP="${_CACHE}.tmp"
_SAMPLES=""
_MAX=60

case "$(uname -s)" in
    Darwin) _PING_W="-W 1000" ;;  # BSD: milliseconds
    *)      _PING_W="-W 1"    ;;  # iputils Linux: seconds
esac

# Single-instance guard
if [ -f "$_PID_FILE" ]; then
    _existing=$(cat "$_PID_FILE" 2>/dev/null)
    if [ -n "$_existing" ] && kill -0 "$_existing" 2>/dev/null; then
        exit 0
    fi
fi
printf '%s\n' "$$" > "$_PID_FILE"

trap 'rm -f "$_PID_FILE" "$_CACHE"' EXIT

while true; do
    # Self-termination: exit when the cockpit session disappears
    if ! tmux has-session -t mume 2>/dev/null; then
        exit 0
    fi

    # Ping and round to integer milliseconds
    # shellcheck disable=SC2086  # word-splitting of $_PING_W is intentional
    _out=$(ping -c 1 $_PING_W mume.org 2>/dev/null)
    _ms=$(printf '%s\n' "$_out" | grep -oE 'time=[0-9.]+ ms' | head -1 \
          | sed 's/time=\([0-9.]*\) ms/\1/')
    if [ -n "$_ms" ]; then
        _sample=$(printf '%.0f' "$_ms")
    else
        _sample="TIMEOUT"
    fi

    # Append to ring buffer, cap at _MAX entries
    if [ -z "$_SAMPLES" ]; then
        _SAMPLES="$_sample"
    else
        _SAMPLES="${_SAMPLES},${_sample}"
    fi

    _count=$(printf '%s' "$_SAMPLES" | awk -F',' '{print NF}')
    if [ "$_count" -gt "$_MAX" ]; then
        _SAMPLES=$(printf '%s' "$_SAMPLES" | awk -F',' -v max="$_MAX" '{
            n = NF; start = n - max + 1; s = ""
            for (i = start; i <= n; i++) { if (s != "") s = s ","; s = s $i }
            print s
        }')
    fi

    # Compute quality label
    _quality=""
    _total=$(printf '%s' "$_SAMPLES" | awk -F',' '{print NF}')
    _losses=$(printf '%s' "$_SAMPLES" | tr ',' '\n' | grep -c '^TIMEOUT$')

    if [ "$_total" -ge 10 ]; then
        _loss_pct=$(( _losses * 100 / _total ))

        if [ "$_loss_pct" -ge 80 ]; then
            _quality="dead"
        else
            mapfile -t _NUMS < <(printf '%s' "$_SAMPLES" | tr ',' '\n' | grep -v '^TIMEOUT$' | sort -n)
            _n=${#_NUMS[@]}
            if [ "$_n" -lt 5 ]; then
                _quality="poor"
            else
                _p50_idx=$(( _n / 2 ))
                _p95_idx=$(( _n * 95 / 100 ))
                [ "$_p95_idx" -ge "$_n" ] && _p95_idx=$(( _n - 1 ))
                _p50=${_NUMS[$_p50_idx]}
                _p95=${_NUMS[$_p95_idx]}
                _spread=$(( _p95 - _p50 ))

                if   [ "$_spread" -lt   8 ] && [ "$_loss_pct" -eq  0 ]; then _quality="stable"
                elif [ "$_spread" -lt  20 ] && [ "$_loss_pct" -lt  5 ]; then _quality="ok"
                elif [ "$_spread" -lt  50 ] && [ "$_loss_pct" -lt 15 ]; then _quality="jittery"
                elif [ "$_spread" -lt 120 ] && [ "$_loss_pct" -lt 30 ]; then _quality="spiking"
                else _quality="poor"
                fi
            fi
        fi
    fi

    # Write cache atomically
    {
        printf 'latest=%s\n' "$_sample"
        printf 'quality=%s\n' "$_quality"
        printf 'samples=%s\n' "$_SAMPLES"
    } > "$_TMP" && mv "$_TMP" "$_CACHE"

    sleep 1
done
