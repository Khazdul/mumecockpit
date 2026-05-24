# bridge/launcher/menu_chrome.py — shared menu chrome helpers.
#
# Pure functions that emit prompt_toolkit-style fragment lists / tuples
# for the title block, footer block, `<< label >>` menu row, and
# three-state button cell used by the launcher (launcher.py) and the
# in-game popup (ingame_menu.py). No prompt_toolkit import — fragments
# are plain `(style, text)` tuples (or 3-tuples carrying a mouse
# handler) the caller appends to its own frags list and the styles come
# from palette.py. No global state.

from palette import (
    C_ACTIVE,
    C_BUTTON_ACTIVE_FOCUSED,
    C_BUTTON_ACTIVE_UNFOCUSED,
    C_BUTTON_DISABLED,
    C_BUTTON_INACTIVE,
    C_CURSOR_CELL,
    C_HINT,
    C_HOVER,
    C_ITEM,
    C_SECTION,
)


_BUTTON_STYLES = {
    "inactive":           C_BUTTON_INACTIVE,
    "hover":              C_BUTTON_ACTIVE_UNFOCUSED,
    "selected_unfocused": C_BUTTON_ACTIVE_UNFOCUSED,
    "selected_focused":   C_BUTTON_ACTIVE_FOCUSED,
    "disabled":           C_BUTTON_DISABLED,
}


def _attach(frags, mouse_handler):
    """Return `frags` as 3-tuples carrying `mouse_handler`, or unchanged
    when no handler was provided."""
    if mouse_handler is None:
        return frags
    return [(f[0], f[1], mouse_handler) for f in frags]


def title_block(title, term_cols, blank_above, mouse_handler=None):
    """Fragments for a centred title row plus surrounding blanks.

    Emits `blank_above` blank rows, then `title` centred in `term_cols`
    cells and styled `C_SECTION`, then one trailing blank row.

    `title` is already decorated (e.g. "─── Panes ───"); the helper does
    not add the dashes. `blank_above` is 2 for the launcher, 1 for the
    popup. Total visual rows produced = blank_above + 2.

    When `mouse_handler` is given, every emitted fragment carries it —
    callers use this to attach a clear-hover handler to the title-block
    chrome so MOUSE_MOVE above the first menu row resets the frame's
    hover index instead of leaving the previous row highlighted.
    """
    frags = []
    for _ in range(blank_above):
        frags.append(("", "\n"))
    pad = " " * max(0, (term_cols - len(title)) // 2)
    frags.append(("", pad))
    frags.append((C_SECTION, title))
    frags.append(("", "\n"))
    frags.append(("", "\n"))
    return _attach(frags, mouse_handler)


def title_block_height(blank_above):
    """Visual-row count produced by `title_block` for the same
    `blank_above`. Callers use it to compute the content row count they
    pass into `footer_block`."""
    return blank_above + 2


def footer_block(footer_text, term_cols, term_rows, content_rows,
                 mouse_handler=None):
    """Fragments that anchor `footer_text` on the final terminal row.

    `content_rows` is the number of visual rows the frame already
    occupies above the footer (title block + body). The helper emits
    `max(0, term_rows - content_rows - 1)` blank rows, then `footer_text`
    centred in `term_cols` and styled `C_HINT`. When content fills or
    overflows the terminal, the pad is zero — never negative.

    When `mouse_handler` is given, every emitted fragment carries it —
    callers use this to attach a clear-hover handler to the footer
    chrome so MOUSE_MOVE below the last menu row resets the frame's
    hover index instead of leaving the previous row highlighted.
    """
    frags = []
    pad_rows = max(0, term_rows - content_rows - 1)
    for _ in range(pad_rows):
        frags.append(("", "\n"))
    pad = " " * max(0, (term_cols - len(footer_text)) // 2)
    frags.append(("", pad))
    frags.append((C_HINT, footer_text))
    return _attach(frags, mouse_handler)


def menu_row(label, state, mouse_handler=None, inactive_style=C_ITEM):
    """Fragments for one `<< label >>` selectable menu row.

    The label is emitted unpadded — the row is `len(label) + 6` cells
    wide and symmetric, so the `<< >>` arrows sit one space off the
    label (`<< Enter MUME >>`, never `<< Enter MUME      >>`). The
    label never shifts horizontally between states because the prefix
    and suffix are the same width (3 cells) in every state.

    `state ∈ {"inactive", "hover", "selected"}`:
      - `selected`  — `<<` / `>>` arrows in gold (`C_CURSOR_CELL`),
                       label in `C_ACTIVE`. Selection (keyboard cursor)
                       wins over hover.
      - `hover`     — three-space prefix / suffix, label in `C_HOVER`
                       (text lightens — the pre-P3 hover behaviour).
      - `inactive`  — three-space prefix / suffix, label in
                       `inactive_style` (`C_ITEM` by default; callers
                       may override to dim a row, e.g. with `C_HINT`).

    `label` is composed by the caller, including any `[ ]` / `( )`
    glyph. To make leading glyphs stack vertically (glyph menus), the
    caller computes the widest *composed* row in the frame and
    prepends a per-row left margin so the whole block shares one left
    edge; plain `<< label >>` menus instead centre each row
    individually.

    When `mouse_handler` is given, every fragment is emitted as a
    3-tuple carrying it.
    """
    if state == "selected":
        prefix = (C_CURSOR_CELL, "<< ")
        body   = (C_ACTIVE,      label)
        suffix = (C_CURSOR_CELL, " >>")
    elif state == "hover":
        prefix = ("",            "   ")
        body   = (C_HOVER,       label)
        suffix = ("",            "   ")
    else:
        prefix = ("",            "   ")
        body   = (inactive_style, label)
        suffix = ("",            "   ")

    return _attach([prefix, body, suffix], mouse_handler)


def button_fragment(label, width, state):
    """A single `(style, text)` fragment for one three-state button cell.

    `label` is centred in `width` cells; labels longer than `width` are
    truncated. `state` is one of `inactive`, `hover`,
    `selected_unfocused`, `selected_focused`, `disabled`. The caller is
    responsible for attaching any mouse_handler — this helper returns a
    bare 2-tuple so it can be wrapped into a 3-tuple later if needed.
    """
    if len(label) >= width:
        text = label[:width]
    else:
        pad = width - len(label)
        left = pad // 2
        right = pad - left
        text = " " * left + label + " " * right
    return (_BUTTON_STYLES[state], text)
