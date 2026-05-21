"""Pure windowing computation for the History frame's filter pill row.

Used by the launcher's `_history_filter_pills_text` renderer. Imports
nothing from prompt_toolkit so the helpers can be unit-tested directly
(see `tests/test_history_filter.py`).

Layout terms (matching docs/launcher.md history section):
- `pill_widths`: list of positive ints, each pill's total cell width
  including its own padding (e.g. `"  All  "` is 7).
- `available_width`: the terminal width the row paints into.
- `SEP_W`: 2-cell gap between adjacent pills.
- `EDGE_SLOT_W`: 2-cell slot at each row edge that holds the `‹` / `›`
  arrow glyph (or blank when nothing is hidden on that side). The slots
  are always reserved when the row overflows, so pill positions don't
  jump as the arrows appear and disappear.
"""

SEP_W = 2
EDGE_SLOT_W = 2


def total_row_width(pill_widths):
    """Width of the full pill row laid out flat (no arrow slots)."""
    n = len(pill_widths)
    if n == 0:
        return 0
    return sum(pill_widths) + SEP_W * (n - 1)


def fits(pill_widths, available_width):
    """True when the entire pill row fits inside available_width."""
    return total_row_width(pill_widths) <= available_width


def max_offset(pill_widths, available_width):
    """Largest pill index `start` such that pills [start..n-1] still fit in
    the usable window (available width minus the two arrow slots).

    Returns 0 when the row fits without overflow.
    """
    n = len(pill_widths)
    if n == 0:
        return 0
    if fits(pill_widths, available_width):
        return 0
    usable = max(0, available_width - 2 * EDGE_SLOT_W)
    start = n - 1
    used = pill_widths[start]
    while start > 0:
        prev = pill_widths[start - 1]
        if used + SEP_W + prev <= usable:
            used += SEP_W + prev
            start -= 1
        else:
            break
    return start


def compute_window(pill_widths, available_width, offset):
    """Compute the visible pill window starting from `offset`.

    Returns (start, end, left_arrow, right_arrow, overflows):
        start, end: visible pill index range (end exclusive). `start` may
            differ from `offset` if `offset` was clamped (negative or
            past the rightmost valid pan position).
        left_arrow: True iff hidden pills exist to the left (start > 0).
        right_arrow: True iff hidden pills exist to the right (end < n).
        overflows: True iff the full row does not fit and arrow slots are
            reserved.

    Pure: caller owns the offset state.
    """
    n = len(pill_widths)
    if n == 0:
        return 0, 0, False, False, False
    if fits(pill_widths, available_width):
        return 0, n, False, False, False

    usable = max(0, available_width - 2 * EDGE_SLOT_W)
    mx = max_offset(pill_widths, available_width)
    start = max(0, min(int(offset), mx))

    end = start
    used = 0
    while end < n:
        w = pill_widths[end]
        sep = SEP_W if end > start else 0
        if used + sep + w <= usable:
            used += sep + w
            end += 1
        else:
            break

    # Degenerate: a single pill is wider than usable. Show it anyway so
    # the row never renders empty (the cursor still has somewhere to land).
    if end == start:
        end = start + 1

    return start, end, start > 0, end < n, True


def scroll_to_cursor(pill_widths, available_width, cursor, offset):
    """Minimal offset adjustment so that pill `cursor` is fully visible.

    Mirrors the keyboard-scroll contract: if the cursor is already inside
    the window at `offset`, the offset is unchanged. Otherwise the window
    pans by whole pills, the minimum needed to bring the cursor pill into
    view.

    Pure: caller owns the offset state.
    """
    n = len(pill_widths)
    if n == 0:
        return 0
    if fits(pill_widths, available_width):
        return 0
    cursor = max(0, min(cursor, n - 1))
    start, end, _, _, _ = compute_window(pill_widths, available_width, offset)
    if start <= cursor < end:
        return start

    if cursor < start:
        # Pan left: cursor becomes the leftmost visible pill.
        return cursor

    # cursor >= end → pan right minimally. Walk left from cursor adding
    # pills while they still fit; the resulting start is the largest
    # offset that still places cursor as the rightmost visible pill.
    usable = max(0, available_width - 2 * EDGE_SLOT_W)
    new_start = cursor
    used = pill_widths[new_start]
    while new_start > 0:
        prev = pill_widths[new_start - 1]
        if used + SEP_W + prev <= usable:
            used += SEP_W + prev
            new_start -= 1
        else:
            break
    return new_start


def pan(pill_widths, available_width, offset, delta):
    """Pan the window by `delta` whole pills (clamped to [0, max_offset]).

    Used by mouse clicks on the edge arrows. Returns the new offset; the
    caller does not mutate the pill cursor.
    """
    if fits(pill_widths, available_width):
        return 0
    mx = max_offset(pill_widths, available_width)
    return max(0, min(int(offset) + int(delta), mx))
