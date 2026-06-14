# bridge/launcher/frame_corners.py — quadrant-corner font-support resolver.
#
# Resolves whether the active terminal font renders the four quadrant
# corner glyphs ▛ ▜ ▙ ▟ (U+259B, U+259C, U+2599, U+259F), so later pane
# rendering can choose seamless quadrant corners over plain half-block
# corners. The result is a single constant ("quadrant" | "block")
# persisted to layout.conf by launcher.py — see _resolve_and_persist_
# frame_corners(), which mirrors the OSC 11 terminal-bg lifecycle
# (ADR 0099).
#
# No prompt_toolkit import, no global state — same discipline as
# foot_config.py. Subprocess + file reads only. fontTools is imported
# lazily and guarded so a missing dependency degrades to "undetermined
# -> block", never crashes startup.
#
# Two parts:
#   (a) active-font-family resolver — reads the terminal config named by
#       MUME_TERMINAL (foot / kitty / alacritty);
#   (b) coverage check — does the FAMILY ITSELF cover all four
#       codepoints? The corners must come from the same font as the
#       half-block edges (▀▄▌▐) to tile seamlessly; a fallback font
#       carrying the corners is not good enough, so the fontconfig
#       backend matches on the returned family name and the fontTools
#       backend loads the family's own file.

import os
import re
import shutil
import subprocess

__all__ = ["CORNER_CODEPOINTS", "resolve_frame_corners", "resolve_and_persist"]


# The four quadrant corner glyphs the cockpit frame would draw.
CORNER_CODEPOINTS = (0x259B, 0x259C, 0x2599, 0x259F)

# Standard font directories scanned by the fontTools fallback backend
# (used only when fc-list is absent — chiefly macOS). "where present":
# non-existent dirs are skipped.
_FONT_DIRS = (
    "/System/Library/Fonts",
    "/Library/Fonts",
    "~/Library/Fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/usr/share/fonts",
)

_FONT_EXTS = (".ttf", ".otf", ".ttc", ".otc")


# ---------------------------------------------------------------------------
# Terminal identity
# ---------------------------------------------------------------------------
def _terminal_name():
    """Map MUME_TERMINAL to a known terminal id, or None when unknown.

    The Windows/WSLg deployment sets `foot-managed` (ADR 0104); treat it
    and a bare `foot` as foot. Any other value, or the variable absent,
    is an unknown terminal -> caller resolves family = None -> block."""
    val = (os.environ.get("MUME_TERMINAL") or "").strip().lower()
    if val in ("foot", "foot-managed"):
        return "foot"
    if val == "kitty":
        return "kitty"
    if val == "alacritty":
        return "alacritty"
    return None


# ---------------------------------------------------------------------------
# (a) Active-font-family resolvers, one per terminal
# ---------------------------------------------------------------------------
def _read_foot_family():
    """Family in `font=` of ~/.config/foot/foot.ini, size suffix stripped.

    Reuses foot_config's font parser. A missing config file -> None (the
    reader would otherwise hand back foot's `monospace` default, which is
    not what is actually configured)."""
    path = os.path.expanduser("~/.config/foot/foot.ini")
    if not os.path.exists(path):
        return None
    try:
        import foot_config
    except ImportError:
        return None
    try:
        cfg = foot_config.read_settings()
    except Exception:
        return None
    family = (getattr(cfg, "family", "") or "").strip()
    return family or None


def _read_kitty_family():
    """`font_family` value from ~/.config/kitty/kitty.conf, or None."""
    path = os.path.expanduser("~/.config/kitty/kitty.conf")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split(None, 1)
                if len(parts) == 2 and parts[0] == "font_family":
                    family = parts[1].strip()
                    return family or None
    except OSError:
        return None
    return None


def _toml_unquote(token):
    """Strip a TOML string's surrounding quotes; bare tokens pass through.
    A trailing comment on a bare token is dropped."""
    token = token.strip()
    if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
        return token[1:-1].strip() or None
    token = token.split("#", 1)[0].strip()
    return token or None


def _scan_alacritty_family(text):
    """Fallback scanner for alacritty.toml when tomllib is unavailable
    (Python < 3.11). Handles both the `[font.normal]` table form and the
    inline `normal = { family = "X" }` form under `[font]`."""
    current = None
    val_re = re.compile(r'family\s*=\s*("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^#\s]+)')
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current == "font.normal":
            m = val_re.match(line)
            if m:
                return _toml_unquote(m.group(1))
        elif current == "font":
            m = re.match(r'normal\s*=\s*\{(.+)\}', line)
            if m:
                fm = val_re.search(m.group(1))
                if fm:
                    return _toml_unquote(fm.group(1))
    return None


def _read_alacritty_family():
    """[font].normal.family from ~/.config/alacritty/alacritty.toml, or None."""
    path = os.path.expanduser("~/.config/alacritty/alacritty.toml")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    try:
        import tomllib
    except ImportError:
        return _scan_alacritty_family(text)
    try:
        data = tomllib.loads(text)
    except Exception:
        return _scan_alacritty_family(text)
    try:
        family = data["font"]["normal"]["family"]
    except (KeyError, TypeError):
        return None
    if isinstance(family, str) and family.strip():
        return family.strip()
    return None


def _resolve_family(terminal):
    if terminal == "foot":
        return _read_foot_family()
    if terminal == "kitty":
        return _read_kitty_family()
    if terminal == "alacritty":
        return _read_alacritty_family()
    return None


# ---------------------------------------------------------------------------
# (b) Coverage check — does the family itself cover all four codepoints?
# ---------------------------------------------------------------------------
def _fc_list_available():
    return shutil.which("fc-list") is not None


def _covered_fontconfig(family, codepoints):
    """fontconfig backend. A codepoint is covered iff
    `fc-list :family=<family>:charset=<cp> family` returns a line whose
    family equals <family> (case-insensitive) — i.e. the family's own
    file carries the glyph, not a fallback. Returns True/False, or None
    if fc-list errors out."""
    target = family.strip().lower()
    for cp in codepoints:
        pattern = f":family={family}:charset={cp:04X}"
        try:
            result = subprocess.run(
                ["fc-list", pattern, "family"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        hit = False
        for line in result.stdout.splitlines():
            for name in line.split(","):
                if name.strip().lower() == target:
                    hit = True
                    break
            if hit:
                break
        if not hit:
            return False
    return True


def _fonttools_available():
    try:
        import fontTools  # noqa: F401
    except Exception:
        return False
    return True


def _font_family_names(path):
    """Family names (nameID 1 and 16) from a font file's name table."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return []
    try:
        font = TTFont(path, fontNumber=0, lazy=True)
    except Exception:
        return []
    out = []
    try:
        name_table = font["name"]
        for rec in name_table.names:
            if rec.nameID in (1, 16):
                try:
                    out.append(rec.toUnicode())
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        try:
            font.close()
        except Exception:
            pass
    return out


def _find_font_file(family):
    """Locate the file whose own family name matches `family`
    (case-insensitive) by scanning the standard font dirs. None if no
    file matches."""
    target = family.strip().lower()
    for d in _FONT_DIRS:
        root = os.path.expanduser(d)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, filenames in os.walk(root):
            for fn in filenames:
                if not fn.lower().endswith(_FONT_EXTS):
                    continue
                full = os.path.join(dirpath, fn)
                for name in _font_family_names(full):
                    if name.strip().lower() == target:
                        return full
    return None


def _covered_fonttools(family, codepoints):
    """fontTools backend. Locate the family's own file, load its best
    cmap, and check all four codepoints are present. Returns True/False,
    or None (undetermined) when fontTools is missing, no file matches,
    or any read fails."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    path = _find_font_file(family)
    if path is None:
        return None
    try:
        font = TTFont(path, fontNumber=0, lazy=True)
    except Exception:
        return None
    try:
        cmap = font.getBestCmap()
    except Exception:
        cmap = None
    finally:
        try:
            font.close()
        except Exception:
            pass
    if not cmap:
        return None
    return all(cp in cmap for cp in codepoints)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def resolve_frame_corners(setting):
    """Resolve the frame-corner style for the `frame_corners` setting.

    Returns `(resolved, info)`:
      - `resolved` is "quadrant" or "block";
      - `info` is a dict {terminal, font, backend, covered} for logging,
        each a printable token (font/terminal "none" when absent;
        covered "yes" | "no" | "unknown").

    `setting`: "quadrant" forces quadrant, "block" forces block (no font
    check); anything else (including None / invalid) is treated as
    "auto" and runs the resolution chain."""
    setting = (setting or "").strip().lower()
    terminal = _terminal_name()
    info = {
        "terminal": terminal or "none",
        "font": "none",
        "backend": "none",
        "covered": "unknown",
    }

    if setting == "quadrant":
        return "quadrant", info
    if setting == "block":
        return "block", info

    # auto
    family = _resolve_family(terminal)
    if not family:
        return "block", info
    info["font"] = family

    if _fc_list_available():
        info["backend"] = "fontconfig"
        covered = _covered_fontconfig(family, CORNER_CODEPOINTS)
    elif _fonttools_available():
        info["backend"] = "fonttools"
        covered = _covered_fonttools(family, CORNER_CODEPOINTS)
    else:
        info["backend"] = "none"
        covered = None

    if covered is True:
        info["covered"] = "yes"
        return "quadrant", info
    if covered is False:
        info["covered"] = "no"
        return "block", info
    info["covered"] = "unknown"
    return "block", info


# ---------------------------------------------------------------------------
# Resolve + persist (shared by the launcher startup path and the popup's
# live corner-style change)
# ---------------------------------------------------------------------------
def _write_resolved(layout_path, resolved):
    """Append-or-replace `frame_corners_resolved=<resolved>` in layout.conf
    in place. build_initial_layout.sh only seeds missing keys, so this write
    survives layout-conf (re)creation. Never raises."""
    try:
        os.makedirs(os.path.dirname(layout_path), exist_ok=True)
    except OSError:
        pass
    try:
        with open(layout_path) as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        lines = []
    except OSError:
        return
    new_line = f"frame_corners_resolved={resolved}\n"
    replaced = False
    out = []
    for line in lines:
        if line.startswith("frame_corners_resolved="):
            if not replaced:
                out.append(new_line)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(new_line)
    try:
        with open(layout_path, "w") as fh:
            fh.writelines(out)
    except OSError:
        pass


def resolve_and_persist(setting, layout_path):
    """Resolve `setting` (auto/quadrant/block) and persist the result to
    `frame_corners_resolved` in layout.conf. Returns `(resolved, info)` —
    the same pair as `resolve_frame_corners`, so callers can log the
    outcome. Never raises: a failure in the resolver degrades to "block"."""
    try:
        resolved, info = resolve_frame_corners(setting)
    except Exception:
        resolved, info = "block", {
            "terminal": "none", "font": "none",
            "backend": "none", "covered": "unknown",
        }
    _write_resolved(layout_path, resolved)
    return resolved, info
