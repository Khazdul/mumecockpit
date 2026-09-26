# bridge/launcher/log_export.py — Export editor model + exporters.
#
# Pure logic behind the launcher's `export_editor` frame: the exclusion
# ranges and inserted comments a user marks up on a chain log, their
# persistence in a per-chain `.export.json` sidecar, and the two export
# writers (plain text and a self-contained HTML replay player). No
# prompt_toolkit import. See docs/launcher.md "export_editor" and
# docs/runs.md for the sidecar schema.

from __future__ import annotations

import bisect
import html
import json
import os
import re
import textwrap
import time
from dataclasses import dataclass, field

import log_player

_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "templates", "log_replay.html")

FORMATS = ("html", "text")

# Comment playback hold: 2 s to notice it plus ~15 characters/s of
# reading, clamped to 5–20 s.
COMMENT_HOLD_BASE_S  = 2.0
COMMENT_HOLD_MIN_S   = 5.0
COMMENT_HOLD_MAX_S   = 20.0
COMMENT_CHARS_PER_S  = 15.0
COMMENT_MAX_LEN      = 600
COMMENT_PREFIX       = "## "
COMMENT_WRAP_COLS    = 80

# A cut (excluded span) between two kept lines collapses to at most this
# much playback time, so the replay jumps across it without a dead pause.
_CUT_GAP_US = 500_000

_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_FILENAME_BAD_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
@dataclass
class Comment:
    anchor: int     # event index the comment is shown BEFORE; == n → after the last line
    text: str


@dataclass
class ExportEdits:
    """Index-based edit state over a list of `n` log events.

    `excludes` is a sorted list of disjoint half-open `[start, end)` event
    ranges (`end` may equal `n`: excluded to the end of the log).
    `comments` is ordered by anchor; comments sharing an anchor keep
    insertion order."""
    n: int
    excludes: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    title: str = ""
    fmt: str = "html"

    # --- exclusion ---------------------------------------------------------
    def range_at(self, idx):
        """Return the position in `excludes` of the range containing idx,
        or None."""
        starts = [s for s, _ in self.excludes]
        i = bisect.bisect_right(starts, idx) - 1
        if i >= 0 and self.excludes[i][0] <= idx < self.excludes[i][1]:
            return i
        return None

    def is_excluded(self, idx):
        return self.range_at(idx) is not None

    def exclude_from(self, idx):
        """Open an exclusion at `idx`. It runs until the next existing
        exclusion's end (the two merge), or to the end of the log when none
        follows — the `<exclude>` tag with its closing tag still to place.
        No-op when idx is already excluded or out of range."""
        if not (0 <= idx < self.n) or self.is_excluded(idx):
            return
        nxt = next((k for k, (s, _) in enumerate(self.excludes) if s > idx), None)
        if nxt is None:
            self.excludes.append((idx, self.n))
        else:
            self.excludes[nxt] = (idx, self.excludes[nxt][1])
        self.excludes.sort()

    def stop_excluding(self, idx):
        """Close the exclusion containing `idx` so `idx` itself is kept
        again (the `</exclude>` tag). Stopping on a range's first line
        removes the range. No-op when idx is not excluded."""
        k = self.range_at(idx)
        if k is None:
            return
        s, _ = self.excludes[k]
        if idx <= s:
            del self.excludes[k]
        else:
            self.excludes[k] = (s, idx)

    def excluded_count(self):
        return sum(e - s for s, e in self.excludes)

    # --- comments ------------------------------------------------------------
    def comments_before(self, anchor):
        return [c for c in self.comments if c.anchor == anchor]

    def add_comment(self, anchor, text, after=None):
        """Insert a comment shown before event `anchor`. `after` (a Comment
        at the same anchor) places the new one directly after it; otherwise
        it goes after every existing comment at that anchor."""
        text = normalise_comment(text)
        if not text:
            return None
        c = Comment(max(0, min(self.n, anchor)), text)
        if after is not None and after in self.comments:
            self.comments.insert(self.comments.index(after) + 1, c)
        else:
            pos = 0
            for i, ex in enumerate(self.comments):
                if ex.anchor <= c.anchor:
                    pos = i + 1
            self.comments.insert(pos, c)
        return c

    def remove_comment(self, comment):
        if comment in self.comments:
            self.comments.remove(comment)

    # --- display / export order -----------------------------------------------
    def items(self):
        """Interleaved display order: ("comment", Comment) rows precede the
        ("event", idx) they anchor to; a final ("end", n) sentinel carries
        comments anchored after the last line."""
        by_anchor = {}
        for c in self.comments:
            by_anchor.setdefault(c.anchor, []).append(c)
        out = []
        for i in range(self.n):
            for c in by_anchor.get(i, ()):
                out.append(("comment", c))
            out.append(("event", i))
        for c in by_anchor.get(self.n, ()):
            out.append(("comment", c))
        out.append(("end", self.n))
        return out


def normalise_comment(text):
    return " ".join((text or "").split())[:COMMENT_MAX_LEN]


def comment_hold_seconds(text):
    """How long replay pauses on a comment: 5–20 s by length."""
    s = COMMENT_HOLD_BASE_S + len(text) / COMMENT_CHARS_PER_S
    return max(COMMENT_HOLD_MIN_S, min(COMMENT_HOLD_MAX_S, s))


def comment_lines(text, width=COMMENT_WRAP_COLS):
    """Wrap a comment into `## `-prefixed lines, every line carrying the
    prefix."""
    body_w = max(10, width - len(COMMENT_PREFIX))
    wrapped = textwrap.wrap(text, body_w, break_long_words=True,
                            break_on_hyphens=False) or [""]
    return [COMMENT_PREFIX + w for w in wrapped]


# ---------------------------------------------------------------------------
# Sidecar persistence — anchors stored as line timestamps so edits survive
# the chain growing (a later stitched run shifts nothing before it).
# ---------------------------------------------------------------------------
def sidecar_path(char_dir, first_run_id):
    return os.path.join(char_dir, first_run_id + ".export.json")


def _ts_to_index(ts_list, ts):
    if ts is None:
        return len(ts_list)
    return max(0, min(len(ts_list), bisect.bisect_left(ts_list, int(ts))))


def load_edits(path, events):
    """Build ExportEdits for `events`, restoring a saved sidecar when one
    exists. Unreadable / malformed sidecars yield empty edits."""
    n = len(events)
    edits = ExportEdits(n=n)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return edits
    if not isinstance(raw, dict):
        return edits
    ts_list = [ev.ts_us for ev in events]
    if isinstance(raw.get("title"), str):
        edits.title = raw["title"]
    if raw.get("format") in FORMATS:
        edits.fmt = raw["format"]
    for pair in raw.get("excludes") or []:
        if not (isinstance(pair, list) and len(pair) == 2):
            continue
        try:
            s = _ts_to_index(ts_list, pair[0])
            e = _ts_to_index(ts_list, pair[1])
        except (TypeError, ValueError):
            continue
        if s < e:
            edits.excludes.append((s, e))
    edits.excludes.sort()
    merged = []
    for s, e in edits.excludes:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    edits.excludes = merged
    for c in raw.get("comments") or []:
        if not isinstance(c, dict) or not isinstance(c.get("text"), str):
            continue
        try:
            anchor = _ts_to_index(ts_list, c.get("before_ts"))
        except (TypeError, ValueError):
            continue
        text = normalise_comment(c["text"])
        if text:
            edits.comments.append(Comment(anchor, text))
    edits.comments.sort(key=lambda c: c.anchor)   # stable: keeps saved order
    return edits


def save_edits(path, edits, events):
    """Persist `edits` (atomic temp + rename). Removes the sidecar when the
    edits are empty and carry no title / non-default format."""
    def ts_at(idx):
        return events[idx].ts_us if idx < len(events) else None
    empty = (not edits.excludes and not edits.comments
             and not edits.title and edits.fmt == "html")
    if empty:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    data = {
        "schema": 1,
        "title": edits.title,
        "format": edits.fmt,
        "excludes": [[ts_at(s), ts_at(e)] for s, e in edits.excludes],
        "comments": [{"before_ts": ts_at(c.anchor), "text": c.text}
                     for c in edits.comments],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Destination paths
# ---------------------------------------------------------------------------
def default_title(character, first_run_id):
    return f"mume-{character}-{first_run_id}"


def safe_filename(title):
    name = _FILENAME_BAD_RE.sub("-", title).strip().strip(".")
    return name or "mume-log"


def dest_path(directory, title, fmt):
    """`<directory>/<title>.<ext>`, suffixed `-2`, `-3`, … on collision —
    an export never overwrites an existing file."""
    ext = ".html" if fmt == "html" else ".txt"
    base = safe_filename(title)
    candidate = os.path.join(directory, base + ext)
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}-{suffix}{ext}")
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Plain text export
# ---------------------------------------------------------------------------
def _event_plain(ev):
    return _ANSI_SGR_RE.sub("", ev.text).rstrip("\r")


def build_text(events, edits):
    """Plain-text export: kept lines (timestamps / ANSI stripped) with
    comments as `## ` lines. A blank line separates stitched runs."""
    out = []
    prev_run = None
    for kind, val in edits.items():
        if kind == "comment":
            out.extend(comment_lines(val.text))
        elif kind == "event":
            if edits.is_excluded(val):
                continue
            ev = events[val]
            if prev_run is not None and ev.run_id != prev_run:
                out.append("")
            prev_run = ev.run_id
            out.append(_event_plain(ev))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# HTML replay export
# ---------------------------------------------------------------------------
def _style_to_css(style):
    css = []
    for part in style.split():
        if part == "bold":
            css.append("font-weight:700")
        elif part == "underline":
            css.append("text-decoration:underline")
        elif part.startswith("fg:"):
            css.append("color:" + part[3:])
        elif part.startswith("bg:"):
            css.append("background:" + part[3:])
    return ";".join(css)


def _frags_to_html(frags):
    out = []
    for style, text in frags:
        t = html.escape(text, quote=False)
        css = _style_to_css(style)
        out.append(f'<span style="{css}">{t}</span>' if css else t)
    return "".join(out)


def _marker_event_indices(events, marker_events):
    """(letter, event_index, title) per tracked event, anchored to the
    content-matched line for pkill / char_death and the nearest line by
    time otherwise — the same rules as the in-launcher player."""
    labels = {"pkill": "PvP kill", "char_death": "Death", "death": "Death",
              "achievement": "Achievement", "level_up": "Level up"}
    ts_list = [ev.ts_us for ev in events]
    out = []
    for kind, ts, ident in marker_events:
        letter = log_player.MARKER_KIND_TO_LETTER.get(kind)
        if letter is None or not events:
            continue
        matched = log_player.match_event_line_ts_us(events, kind, int(ts), ident)
        target = matched if matched is not None else int(ts) * 1_000_000
        i = bisect.bisect_left(ts_list, target)
        if i >= len(ts_list):
            i = len(ts_list) - 1
        elif i > 0 and (ts_list[i] - target) > (target - ts_list[i - 1]):
            i -= 1
        title = labels.get(kind, kind) + (f": {ident}" if ident else "")
        out.append((letter, i, title))
    return out


def build_html_data(events, edits, character, start_level=None,
                    start_ts=None, marker_events=()):
    """Replay payload: kept lines + comments in display order, their
    playback offsets (ms), comment holds (ms, keyed by row) and strip
    markers. Gaps over the player cap collapse to 0; cuts to ≤0.5 s;
    comments take no timeline time (they hold in real time)."""
    lines, offsets, holds = [], [], {}
    event_row = {}
    offset_us = 0
    prev_idx = None
    for kind, val in edits.items():
        if kind == "comment":
            holds[len(lines)] = int(comment_hold_seconds(val.text) * 1000)
            body = "\n".join(html.escape(l, quote=False) for l in comment_lines(val.text))
            lines.append(f'<span class="cm">{body}</span>')
            offsets.append(offset_us // 1000)
        elif kind == "event":
            if edits.is_excluded(val):
                continue
            ev = events[val]
            if prev_idx is not None:
                gap = ev.ts_us - events[prev_idx].ts_us
                if gap < 0:
                    gap = 0
                if val - prev_idx > 1:
                    gap = min(gap, _CUT_GAP_US)
                elif gap > log_player._PLAYBACK_GAP_CAP_US:
                    gap = 0
                offset_us += gap
            prev_idx = val
            event_row[val] = len(lines)
            lines.append(_frags_to_html(ev.fragments))
            offsets.append(offset_us // 1000)
    markers = []
    for letter, idx, title in _marker_event_indices(events, marker_events):
        row = event_row.get(idx)
        if row is not None:
            markers.append({"l": letter, "o": offsets[row], "t": title})
    return {
        "title": edits.title,
        "char": character,
        "level": start_level,
        "date": (time.strftime("%Y-%m-%d %H:%M", time.localtime(start_ts))
                 if start_ts else ""),
        "offsets": offsets,
        "lines": lines,
        "holds": holds,
        "markers": markers,
    }


def build_html(data, template_path=_TEMPLATE):
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    title = html.escape(data.get("title") or f"{data.get('char', '')} — MUME log")
    return tpl.replace("/*__DATA__*/null", payload).replace("__TITLE__", title)


def write_export(dest, events, edits, character, start_level=None,
                 start_ts=None, marker_events=()):
    """Render `edits.fmt` and write it to `dest`. Raises OSError."""
    if edits.fmt == "html":
        if not any(not edits.is_excluded(i) for i in range(len(events))):
            raise OSError("everything is excluded")
        data = build_html_data(events, edits, character, start_level,
                               start_ts, marker_events)
        content = build_html(data)
    else:
        content = build_text(events, edits)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
