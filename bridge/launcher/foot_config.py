# bridge/launcher/foot_config.py — pure foot.ini reader / writer.
#
# Single home for foot.ini-format knowledge. Imported by launcher.py
# (Options → Terminal) to display and edit the managed terminal
# settings when the cockpit runs under the foot/WSLg deployment.
#
# The writer is a managed-keys read/modify/write over a fixed set of
# (section, key) pairs — see ADR 0107. For each managed key it
# rewrites the line in place when present, appends to the section
# when the key is absent, or appends section + line at EOF when the
# section is absent. Every non-managed line is preserved verbatim.
# The write stays atomic (temp file + rename).
#
# No prompt_toolkit import, no global state — same discipline as
# panes_grid.py. See ADR 0104 for the MUME_TERMINAL contract that
# gates the launcher submenu using this module.

import os
import subprocess
import tempfile
from dataclasses import dataclass

__all__ = [
    "TerminalConfig",
    "DEFAULT_FOOT_CONFIG_PATH",
    "read_settings",
    "write_settings",
    "list_monospace_fonts",
]


DEFAULT_FOOT_CONFIG_PATH = "~/.config/foot/foot.ini"


# Managed (section, key) pairs. Section "" denotes the implicit leading
# section (everything above the first `[header]`). Order is the order
# in which absent keys would be materialised — kept stable for review.
_MANAGED_KEYS = [
    ("",       "font"),
    ("",       "pad"),
    ("",       "initial-window-mode"),
    ("",       "initial-window-size-pixels"),
    ("colors", "alpha"),
    ("colors", "background"),
    ("cursor", "style"),
    ("cursor", "blink"),
]
_MANAGED_KEY_SET = set(_MANAGED_KEYS)

# Defaults applied when a managed key is absent from foot.ini. These
# mirror foot's documented defaults so an absent key never changes
# observable behaviour. `initial-window-size-pixels` is the one
# exception — foot has no documented pixel default, so a defensive
# fallback is used; the Windows installer overwrites it.
_DEFAULTS = {
    ("",       "font"):                       "monospace",
    ("",       "pad"):                        "0x0",
    ("",       "initial-window-mode"):        "windowed",
    ("",       "initial-window-size-pixels"): "1280x800",
    ("colors", "alpha"):                      "1.0",
    ("colors", "background"):                 "242424",
    ("cursor", "style"):                      "block",
    ("cursor", "blink"):                      "no",
}


@dataclass
class TerminalConfig:
    """Managed foot.ini values. `size` is the numeric point size when
    the `font=` entry carries a cleanly-parseable `size=<n>` attribute
    (int or float), else `None` — foot falls back to its implicit
    default size when absent. Every other field always has a concrete
    value (defaults applied on read)."""
    family:        str
    size:          "float | int | None"
    window_mode:   str   # windowed | maximized | fullscreen
    window_width:  int
    window_height: int
    alpha:         float
    background:    str   # hex RRGGBB, no leading '#'
    pad_x:         int
    pad_y:         int
    cursor_style:  str   # block | beam | underline
    cursor_blink:  bool


def _resolve_path(path):
    return os.path.expanduser(path if path else DEFAULT_FOOT_CONFIG_PATH)


def _section_header(line):
    """If `line` is a `[section]` header, return the section name; else None."""
    s = line.strip()
    if len(s) >= 2 and s.startswith("[") and s.endswith("]"):
        return s[1:-1].strip()
    return None


def _is_assignment(line, key):
    """True if `line` is an uncommented `key=` assignment for `key`."""
    s = line.lstrip()
    if not s or s.startswith("#") or s.startswith(";"):
        return False
    k, eq, _ = s.partition("=")
    return eq == "=" and k.strip() == key


def _assignment_value(line):
    """Return the right-hand side of a `key=value` assignment, stripped."""
    _, _, value = line.partition("=")
    return value.strip()


def _parse_managed_values(text):
    """Walk `text` and capture the first occurrence of each managed key.
    Returns a `{(section, key): raw_value_str}` dict for keys that were
    present. Section tracking starts in the implicit leading section
    (`""`) and switches on each `[header]` line.
    """
    found = {}
    current = ""
    for raw in text.splitlines():
        sec = _section_header(raw)
        if sec is not None:
            current = sec
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        managed_key = (current, key.strip())
        if managed_key in _MANAGED_KEY_SET and managed_key not in found:
            found[managed_key] = value.strip()
    return found


def _parse_size(token):
    """Parse `size=<n>`; return int when whole, float otherwise, or None."""
    try:
        f = float(token)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _parse_font(value):
    """Extract family + size from a foot `font=` value.

    Format: `<family>[:key=value[:key=value...]][,<fallback>...]`. The
    family is the substring before the first `:`. Size comes from the
    `size=` attribute if present and cleanly parseable, else `None`.
    """
    first = value.split(",", 1)[0].strip()
    if not first:
        return _DEFAULTS[("", "font")], None
    parts = first.split(":")
    family = parts[0].strip() or _DEFAULTS[("", "font")]
    size = None
    for attr in parts[1:]:
        k, _, v = attr.partition("=")
        if k.strip() == "size":
            size = _parse_size(v.strip())
            break
    return family, size


def _parse_dim_pair(value, default_w, default_h):
    """Parse `WxH` → (int, int); fall back per-component on parse failure."""
    w_s, _, h_s = value.partition("x")
    try:
        w = int(w_s.strip())
    except ValueError:
        w = default_w
    try:
        h = int(h_s.strip())
    except ValueError:
        h = default_h
    return w, h


def _parse_float(value, default):
    try:
        return float(value)
    except ValueError:
        return default


def _parse_yes_no(value):
    return value.strip().lower() in ("yes", "true", "on", "1")


def _build_config(found):
    """Build a TerminalConfig from raw managed values, applying defaults."""
    def raw(key):
        return found.get(key, _DEFAULTS[key])

    family, size = _parse_font(raw(("", "font")))

    default_pad_w, default_pad_h = _parse_dim_pair(
        _DEFAULTS[("", "pad")], 0, 0,
    )
    pad_x, pad_y = _parse_dim_pair(
        raw(("", "pad")), default_pad_w, default_pad_h,
    )

    default_win_w, default_win_h = _parse_dim_pair(
        _DEFAULTS[("", "initial-window-size-pixels")], 1280, 800,
    )
    win_w, win_h = _parse_dim_pair(
        raw(("", "initial-window-size-pixels")), default_win_w, default_win_h,
    )

    window_mode = raw(("", "initial-window-mode")).strip().lower()
    if window_mode not in ("windowed", "maximized", "fullscreen"):
        window_mode = _DEFAULTS[("", "initial-window-mode")]

    alpha = _parse_float(
        raw(("colors", "alpha")),
        _parse_float(_DEFAULTS[("colors", "alpha")], 1.0),
    )

    background = raw(("colors", "background")).strip().lstrip("#")

    cursor_style = raw(("cursor", "style")).strip().lower()
    if cursor_style not in ("block", "beam", "underline"):
        cursor_style = _DEFAULTS[("cursor", "style")]

    cursor_blink = _parse_yes_no(raw(("cursor", "blink")))

    return TerminalConfig(
        family=family,
        size=size,
        window_mode=window_mode,
        window_width=win_w,
        window_height=win_h,
        alpha=alpha,
        background=background,
        pad_x=pad_x,
        pad_y=pad_y,
        cursor_style=cursor_style,
        cursor_blink=cursor_blink,
    )


def read_settings(path=None):
    """Return a TerminalConfig built from a foot.ini.

    `path` defaults to `~/.config/foot/foot.ini`. A missing file or
    any absent managed key resolves to that key's default — the
    function never raises for these expected cases.
    """
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    return _build_config(_parse_managed_values(text))


def list_monospace_fonts():
    """Return a sorted, de-duplicated list of installed monospace family names.

    Invokes `fc-list :spacing=mono` and reduces the per-style lines to a
    single entry per family — the canonical (first comma-separated)
    family name from each line. Missing fc-list, a non-zero exit, or
    empty output all return an empty list — never raises.
    """
    try:
        result = subprocess.run(
            ["fc-list", ":spacing=mono"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    families = set()
    for line in result.stdout.splitlines():
        # fc-list line: "<path>: <family>[,<alias>...][:style=...][:...]"
        if ": " not in line:
            continue
        _, _, rest = line.partition(": ")
        # Drop trailing attributes (style, lang, etc.) after the first ":".
        family_section = rest.split(":", 1)[0].strip()
        if not family_section:
            continue
        # The canonical family is the first comma-separated entry —
        # later entries are localized aliases.
        family = family_section.split(",", 1)[0].strip()
        if family:
            families.add(family)
    return sorted(families)


def _format_font(family, size):
    if size is None:
        return f"font={family}"
    return f"font={family}:size={size}"


def _format_float(value):
    """Compact float string that always carries a decimal point.

    `str(1.0)` already returns `"1.0"`; the helper exists so all
    managed-key formatting goes through one named function.
    """
    return str(float(value))


def _format_line(managed_key, config):
    section, key = managed_key
    if key == "font":
        return _format_font(config.family, config.size)
    if key == "pad":
        return f"pad={int(config.pad_x)}x{int(config.pad_y)}"
    if key == "initial-window-mode":
        return f"initial-window-mode={config.window_mode}"
    if key == "initial-window-size-pixels":
        return (f"initial-window-size-pixels="
                f"{int(config.window_width)}x{int(config.window_height)}")
    if section == "colors" and key == "alpha":
        return f"alpha={_format_float(config.alpha)}"
    if section == "colors" and key == "background":
        return f"background={config.background}"
    if section == "cursor" and key == "style":
        return f"style={config.cursor_style}"
    if section == "cursor" and key == "blink":
        return f"blink={'yes' if config.cursor_blink else 'no'}"
    raise KeyError(managed_key)


def _atomic_write(path, text):
    """Write `text` to `path` atomically via temp file + rename."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".foot.ini.", suffix=".tmp", dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _scan_existing(lines):
    """Single pass over `lines` collecting structural data for write_settings.

    Returns `(matched, sections_present, section_end)` where:
      - `matched` maps each managed key found in-file to its line index
        (first occurrence wins, mirroring the reader);
      - `sections_present` is the set of section names seen — the
        implicit leading section `""` is always present;
      - `section_end` maps each present section name to the index AT
        which an appended line should be inserted (one past the section's
        last content line; either the next section header or len(lines)).
    """
    matched = {}
    sections_present = {""}
    section_end = {"": len(lines)}
    current = ""
    for i, raw in enumerate(lines):
        sec = _section_header(raw)
        if sec is not None:
            # The previous section ends here (before this header).
            section_end[current] = i
            current = sec
            sections_present.add(sec)
            section_end[sec] = len(lines)
            continue
        for key in _MANAGED_KEYS:
            if key in matched:
                continue
            sec_name, k_name = key
            if sec_name == current and _is_assignment(raw, k_name):
                matched[key] = i
                break
    return matched, sections_present, section_end


def write_settings(config, path=None):
    """Write `config` to a foot.ini, touching only the managed key set.

    Per ADR 0107: for each managed (section, key) pair, rewrite the
    line in place when present; otherwise append it at the end of the
    section, creating the section header at EOF if the section is
    absent. All non-managed lines are preserved verbatim. The write
    is atomic (temp file + rename).
    """
    resolved = _resolve_path(path)

    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""

    lines = text.splitlines(keepends=True)
    matched, sections_present, section_end = _scan_existing(lines)

    # Step 1: rewrite matched lines in place, preserving the original EOL.
    out = list(lines)
    for key, idx in matched.items():
        eol = "\n" if out[idx].endswith(("\n", "\r")) else ""
        out[idx] = _format_line(key, config) + eol

    # Step 2: group unmatched keys by section so they share an insertion
    # point (existing sections) or a freshly-appended header (new sections).
    unmatched_by_section = {}
    for key in _MANAGED_KEYS:
        if key in matched:
            continue
        sec_name, _ = key
        unmatched_by_section.setdefault(sec_name, []).append(key)

    # Step 3: insertions into existing sections. Process highest index
    # first so earlier insertions don't shift later target indices.
    existing_inserts = []  # (insert_idx, [formatted_lines])
    new_section_keys = []  # [(section_name, [keys])]
    for sec_name, keys in unmatched_by_section.items():
        if sec_name in sections_present:
            insert_idx = section_end[sec_name]
            formatted_lines = [_format_line(k, config) + "\n" for k in keys]
            existing_inserts.append((insert_idx, formatted_lines))
        else:
            new_section_keys.append((sec_name, keys))

    for insert_idx, formatted_lines in sorted(
            existing_inserts, key=lambda item: item[0], reverse=True):
        # Ensure the line preceding the insertion terminates cleanly so
        # the appended line lands on its own row.
        if insert_idx > 0:
            prev = out[insert_idx - 1]
            if not prev.endswith(("\n", "\r")):
                out[insert_idx - 1] = prev + "\n"
        for line in reversed(formatted_lines):
            out.insert(insert_idx, line)

    # Step 4: append any wholly-new sections at EOF.
    if new_section_keys:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] = out[-1] + "\n"
        for sec_name, keys in new_section_keys:
            if out:
                out.append("\n")
            out.append(f"[{sec_name}]\n")
            for k in keys:
                out.append(_format_line(k, config) + "\n")

    _atomic_write(resolved, "".join(out))
