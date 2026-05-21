# bridge/launcher/menu_chrome.py — shared menu chrome helpers.
#
# Pure functions that emit prompt_toolkit-style fragment lists / tuples
# for the title block, footer block, and three-state button cell used by
# the launcher (launcher.py) and the in-game popup (ingame_menu.py).
# No prompt_toolkit import — fragments are plain `(style, text)` tuples
# the caller appends to its own frags list and the styles come from
# palette.py. No global state.

from palette import (
    C_BUTTON_ACTIVE_FOCUSED,
    C_BUTTON_ACTIVE_UNFOCUSED,
    C_BUTTON_DISABLED,
    C_BUTTON_INACTIVE,
    C_HINT,
    C_SECTION,
)


_BUTTON_STYLES = {
    "inactive":           C_BUTTON_INACTIVE,
    "hover":              C_BUTTON_ACTIVE_UNFOCUSED,
    "selected_unfocused": C_BUTTON_ACTIVE_UNFOCUSED,
    "selected_focused":   C_BUTTON_ACTIVE_FOCUSED,
    "disabled":           C_BUTTON_DISABLED,
}


def title_block(title, term_cols, blank_above):
    """Fragments for a centred title row plus surrounding blanks.

    Emits `blank_above` blank rows, then `title` centred in `term_cols`
    cells and styled `C_SECTION`, then one trailing blank row.

    `title` is already decorated (e.g. "─── Panes ───"); the helper does
    not add the dashes. `blank_above` is 2 for the launcher, 1 for the
    popup. Total visual rows produced = blank_above + 2.
    """
    frags = []
    for _ in range(blank_above):
        frags.append(("", "\n"))
    pad = " " * max(0, (term_cols - len(title)) // 2)
    frags.append(("", pad))
    frags.append((C_SECTION, title))
    frags.append(("", "\n"))
    frags.append(("", "\n"))
    return frags


def title_block_height(blank_above):
    """Visual-row count produced by `title_block` for the same
    `blank_above`. Callers use it to compute the content row count they
    pass into `footer_block`."""
    return blank_above + 2


def footer_block(footer_text, term_cols, term_rows, content_rows):
    """Fragments that anchor `footer_text` on the final terminal row.

    `content_rows` is the number of visual rows the frame already
    occupies above the footer (title block + body). The helper emits
    `max(0, term_rows - content_rows - 1)` blank rows, then `footer_text`
    centred in `term_cols` and styled `C_HINT`. When content fills or
    overflows the terminal, the pad is zero — never negative.
    """
    frags = []
    pad_rows = max(0, term_rows - content_rows - 1)
    for _ in range(pad_rows):
        frags.append(("", "\n"))
    pad = " " * max(0, (term_cols - len(footer_text)) // 2)
    frags.append(("", pad))
    frags.append((C_HINT, footer_text))
    return frags


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
