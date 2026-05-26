# bridge/launcher/foot_config.py — pure foot.ini reader.
#
# Single home for foot.ini-format knowledge. Imported by launcher.py
# (Options → Terminal) to display the configured font when the cockpit
# runs under the foot/WSLg managed-terminal deployment. Phase 3 will
# add a `write_font(...)` here that targets the same configurable
# path.
#
# No prompt_toolkit import, no global state — same discipline as
# panes_grid.py. See ADR 0104 for the MUME_TERMINAL contract that
# gates the launcher submenu using this module.

import os
from dataclasses import dataclass

__all__ = ["FontConfig", "DEFAULT_FOOT_CONFIG_PATH", "read_font"]


DEFAULT_FOOT_CONFIG_PATH = "~/.config/foot/foot.ini"


@dataclass
class FontConfig:
    """Parsed primary font from a foot.ini `font=` line.

    `size` is the numeric point size when the entry carries a
    cleanly-parseable `size=<n>` attribute (int or float), else `None`
    — foot falls back to an implicit default size when absent."""
    family: str
    size:   "float | int | None"


def _resolve_path(path):
    return os.path.expanduser(path if path else DEFAULT_FOOT_CONFIG_PATH)


def _iter_font_lines(text):
    """Yield raw `font=...` values from `text`, in file order.

    Skips blank lines, full-line comments (`#`, `;`), and anything that
    isn't a `font=` assignment. Inline comments after the value are not
    stripped — foot itself doesn't document them, and the first
    comma-separated entry parse below tolerates trailing whitespace.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "font":
            continue
        yield value.strip()


def _parse_size(token):
    """Parse `size=<n>`; return int when whole, float otherwise, or None."""
    try:
        f = float(token)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _parse_first_entry(value):
    """Parse the first comma-separated entry of a foot `font=` value.

    Returns `FontConfig | None`. An entry is
    `<family>[:key=value[:key=value...]]`. Family is the substring
    before the first `:`. Size comes from the `size=` attribute if
    present and cleanly parseable.
    """
    first = value.split(",", 1)[0].strip()
    if not first:
        return None
    parts = first.split(":")
    family = parts[0].strip()
    if not family:
        return None
    size = None
    for attr in parts[1:]:
        k, _, v = attr.partition("=")
        if k.strip() == "size":
            size = _parse_size(v.strip())
            break
    return FontConfig(family=family, size=size)


def read_font(path=None):
    """Return the configured primary font from a foot.ini, or `None`.

    `path` defaults to `~/.config/foot/foot.ini`. Missing file, no
    uncommented `font=` line, or an unparseable family all return
    `None` — never raises for these expected cases. The `path`
    parameter exists so the reader is testable and so Phase 3's
    writer can target the same configurable path.
    """
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    for value in _iter_font_lines(text):
        cfg = _parse_first_entry(value)
        if cfg is not None:
            return cfg
    return None
