# bridge/launcher/foot_config.py — pure foot.ini reader / writer.
#
# Single home for foot.ini-format knowledge. Imported by launcher.py
# (Options → Terminal) to display and edit the configured font when the
# cockpit runs under the foot/WSLg managed-terminal deployment. The
# writer is intentionally surgical — Apply owns only the `font=` line
# (ADR 0104); every other line is left untouched.
#
# No prompt_toolkit import, no global state — same discipline as
# panes_grid.py. See ADR 0104 for the MUME_TERMINAL contract that
# gates the launcher submenu using this module.

import os
import subprocess
import tempfile
from dataclasses import dataclass

__all__ = [
    "FontConfig",
    "DEFAULT_FOOT_CONFIG_PATH",
    "read_font",
    "write_font",
    "list_monospace_fonts",
]


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
    parameter exists so the reader is testable and so the writer
    targets the same configurable path.
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


def _format_font_line(family, size):
    return f"font={family}:size={size}"


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


def write_font(family, size, path=None):
    """Rewrite the first uncommented `font=` line in a foot.ini.

    If no such line exists, append one in the implicit main section —
    immediately before the first `[section]` header, or at end of file
    when there are no section headers. Every other line is preserved
    verbatim (ADR 0104 — Apply owns only the `font=` line). Written
    atomically (temp file + rename) per docs/bridge-services.md.
    """
    resolved = _resolve_path(path)
    new_line = _format_font_line(family, size)

    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        # No existing foot.ini — create a minimal one with the font line.
        _atomic_write(resolved, new_line + "\n")
        return

    lines = text.splitlines(keepends=True)
    out_lines = []
    replaced = False
    for line in lines:
        if not replaced:
            stripped = line.lstrip()
            if (stripped and not stripped.startswith("#")
                    and not stripped.startswith(";")):
                key, sep, _value = stripped.partition("=")
                if sep == "=" and key.strip() == "font":
                    eol = "\n" if line.endswith("\n") else ""
                    out_lines.append(new_line + eol)
                    replaced = True
                    continue
        out_lines.append(line)

    if not replaced:
        # Find the first [section] header and insert immediately before
        # it (the implicit main section is everything above the first
        # header in foot.ini). If there are no section headers, append
        # at end of file.
        insert_at = len(out_lines)
        for i, line in enumerate(out_lines):
            if line.lstrip().startswith("["):
                insert_at = i
                break
        # Ensure the previous line ends with a newline before insertion,
        # so the new font line lands on its own row.
        if insert_at > 0:
            prev = out_lines[insert_at - 1]
            if not prev.endswith("\n"):
                out_lines[insert_at - 1] = prev + "\n"
        out_lines.insert(insert_at, new_line + "\n")

    _atomic_write(resolved, "".join(out_lines))
