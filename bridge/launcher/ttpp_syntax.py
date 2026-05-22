# bridge/launcher/ttpp_syntax.py — best-effort lexical tokeniser for the
# profile editor's Editor mode. Pure-Python, no prompt_toolkit dependency;
# returns non-overlapping (start, end, kind) spans that the renderer maps
# to the C_SYN_* palette tokens.
#
# Five kinds — strictly lexical, no grammar awareness:
#   "command" — `#` + identifier, only in command position (logical-line
#               start after optional whitespace, immediately after `{`,
#               or immediately after `;`). Unknown commands and typos
#               highlight too — we never whitelist tt++ command names.
#   "brace"   — every standalone `{` or `}` (1-char span). Braces consumed
#               inside a `${...}` var are NOT re-emitted.
#   "delim"   — every standalone `;` (1-char span). Colouring a literal `;`
#               inside a body is acceptable and expected.
#   "var"     — `$id`, `${...}`, `&id`, `%`+digits, `%`+single regex-special.
#   "code"    — `<...>` short word-char colour codes, `\`+escape (incl.
#               `\xNN`, `\uNNNN`, `\u{...}`, `\UNNNNNN`).
#
# Trade-off recorded in docs/decisions/0089-profile-editor-syntax-highlight.md:
# a real tt++ parser would let us avoid colouring a literal `;` inside an
# action's argument body, but the visual cost of an occasional miscoloured
# delimiter is much smaller than the maintenance cost of carrying a full
# parser here. See the ADR for the rejected alternative.

__all__ = ["tokenize"]


# Single regex-special chars that legitimately follow `%` in tt++ patterns
# (e.g. `%*`, `%.`, `%+`). Letters are deliberately excluded — `%U`, `%T`
# etc. are #format codes, not pattern captures, and not in scope here.
# So are `%-`, `%{`, `%\` etc.: not PCRE meta-chars, just #format/printf
# punctuation that would miscolour as a var.
_PCT_REGEX_SPECIALS = frozenset(".+*?^$|()[]")

# Hex digit set used by `\xNN`, `\uNNNN`, `\UNNNNNN`, and `\u{...}` bodies.
_HEX = frozenset("0123456789abcdefABCDEF")


def _is_id_char(ch):
    """Identifier body characters for tt++ variable names: letters, digits,
    underscore. Matches the manual's `letters, numbers and underscores`
    rule for unbraced `$var` / `&var`."""
    return ch.isalnum() or ch == "_"


def tokenize(text):
    """Return non-overlapping, ascending (start, end, kind) spans covering
    only the tokenised regions of `text`. Gaps between spans are
    default-styled.

    Single left-to-right scan, longest-match. A character consumed by a
    multi-char token is never re-tokenised — `${var}` is one "var" span,
    not three (`var` + two `brace`)."""
    spans = []
    n = len(text)
    i = 0

    # Command position: True at text start, after `\n`, after `{`, and
    # after `;`. Whitespace after any of those does not break the state.
    # Any other character flips it to False.
    cmd_pos = True

    while i < n:
        ch = text[i]

        if ch == "\n":
            cmd_pos = True
            i += 1
            continue

        if ch in " \t":
            # Whitespace preserves cmd_pos.
            i += 1
            continue

        # --- `#command` --------------------------------------------------
        if ch == "#" and cmd_pos:
            j = i + 1
            while j < n and _is_id_char(text[j]):
                j += 1
            if j > i + 1:
                spans.append((i, j, "command"))
                i = j
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # --- braces ------------------------------------------------------
        if ch == "{":
            spans.append((i, i + 1, "brace"))
            i += 1
            cmd_pos = True
            continue

        if ch == "}":
            spans.append((i, i + 1, "brace"))
            i += 1
            cmd_pos = False
            continue

        # --- delim -------------------------------------------------------
        if ch == ";":
            spans.append((i, i + 1, "delim"))
            i += 1
            cmd_pos = True
            continue

        # --- $variable / ${...} -----------------------------------------
        if ch == "$":
            if i + 1 < n and text[i + 1] == "{":
                # Walk to the matching `}` on the same logical line.
                # Unclosed `${` falls back to plain text; the `{` then
                # picks up a normal brace span on the next iteration.
                j = i + 2
                while j < n and text[j] != "}" and text[j] != "\n":
                    j += 1
                if j < n and text[j] == "}":
                    spans.append((i, j + 1, "var"))
                    i = j + 1
                    cmd_pos = False
                    continue
                i += 1
                cmd_pos = False
                continue
            j = i + 1
            while j < n and _is_id_char(text[j]):
                j += 1
            if j > i + 1:
                spans.append((i, j, "var"))
                i = j
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # --- &variable (size-of / index-of) -----------------------------
        if ch == "&":
            j = i + 1
            while j < n and _is_id_char(text[j]):
                j += 1
            if j > i + 1:
                spans.append((i, j, "var"))
                i = j
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # --- %digits or %<single regex-special> -------------------------
        if ch == "%" and i + 1 < n:
            nx = text[i + 1]
            if nx.isdigit():
                j = i + 2
                while j < n and text[j].isdigit():
                    j += 1
                spans.append((i, j, "var"))
                i = j
                cmd_pos = False
                continue
            if nx in _PCT_REGEX_SPECIALS:
                spans.append((i, i + 2, "var"))
                i += 2
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # --- <...> colour / format code ---------------------------------
        # 1-7 word chars inside the angle brackets. Covers `<088>`, `<g00>`,
        # `<aaa>..<fff>`, `<F000>..<FFFF>`, `<F000000>..<FFFFFFF>`, etc.
        if ch == "<":
            j = i + 1
            while j < n and j - (i + 1) < 7 and text[j].isalnum():
                j += 1
            if j > i + 1 and j < n and text[j] == ">":
                spans.append((i, j + 1, "code"))
                i = j + 1
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # --- \escape ----------------------------------------------------
        if ch == "\\" and i + 1 < n:
            nx = text[i + 1]
            # `\xNN` — 1-2 hex digits.
            if nx in ("x", "X"):
                j = i + 2
                while j < n and j - (i + 2) < 2 and text[j] in _HEX:
                    j += 1
                spans.append((i, j, "code"))
                i = j
                cmd_pos = False
                continue
            # `\uNNNN` or `\u{...}`.
            if nx == "u":
                if i + 2 < n and text[i + 2] == "{":
                    j = i + 3
                    while j < n and text[j] != "}" and text[j] != "\n":
                        j += 1
                    if j < n and text[j] == "}":
                        spans.append((i, j + 1, "code"))
                        i = j + 1
                        cmd_pos = False
                        continue
                j = i + 2
                while j < n and j - (i + 2) < 4 and text[j] in _HEX:
                    j += 1
                spans.append((i, j, "code"))
                i = j
                cmd_pos = False
                continue
            # `\UNNNNNN`.
            if nx == "U":
                j = i + 2
                while j < n and j - (i + 2) < 6 and text[j] in _HEX:
                    j += 1
                spans.append((i, j, "code"))
                i = j
                cmd_pos = False
                continue
            # `\a` `\e` `\n` `\t` `\\` `\{` `\}` etc. — any non-newline
            # single char.
            if nx != "\n":
                spans.append((i, i + 2, "code"))
                i += 2
                cmd_pos = False
                continue
            i += 1
            cmd_pos = False
            continue

        # Default: any other character — leaves command position.
        i += 1
        cmd_pos = False

    return spans
