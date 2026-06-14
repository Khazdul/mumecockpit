# bridge/launcher/tests/test_timers_layout_none_token.py — guards the shared
# contract that every Timers-layout parser accepts the "none" colour token
# (any case) alongside an #rrggbb hex. Mirrors the three readers: the
# launcher's _parse_timers_layout, the pane's _load_layout, and the popup's
# _read_timers_layout.

import os
import sys

# Allow `import launcher` / `import ingame_menu` (launcher dir) and
# `import timers_pane` (panes dir) via the launcher's sys.path convention.
_LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PANES_DIR = os.path.join(os.path.dirname(_LAUNCHER_DIR), "panes")
sys.path.insert(0, _LAUNCHER_DIR)
sys.path.insert(0, _PANES_DIR)

import ingame_menu      # noqa: E402
import launcher         # noqa: E402
import timers_pane      # noqa: E402


def _write_conf(path, color):
    with open(path, "w") as fh:
        fh.write("timers_spell_enabled=1\n")
        fh.write(f"timers_spell_color={color}\n")


# ── launcher: _parse_timers_layout(path) ───────────────────────────────
def test_launcher_parser_accepts_none(tmp_path):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "none")
    layout = launcher._parse_timers_layout(str(conf))
    assert layout["spell"]["color"] == "none"


def test_launcher_parser_accepts_none_uppercase(tmp_path):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "NONE")
    layout = launcher._parse_timers_layout(str(conf))
    assert layout["spell"]["color"] == "none"


# ── pane: _load_layout() reads module-global TIMERS_LAYOUT_PATH ─────────
def test_pane_loader_accepts_none(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "none")
    monkeypatch.setattr(timers_pane, "TIMERS_LAYOUT_PATH", str(conf))
    layout, _headers, _compact = timers_pane._load_layout()
    assert layout["spell"]["color"] == "none"


def test_pane_loader_accepts_none_uppercase(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "NONE")
    monkeypatch.setattr(timers_pane, "TIMERS_LAYOUT_PATH", str(conf))
    layout, _headers, _compact = timers_pane._load_layout()
    assert layout["spell"]["color"] == "none"


# ── popup: _read_timers_layout() reads module-global conf path ──────────
def test_popup_reader_accepts_none(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "none")
    monkeypatch.setattr(ingame_menu, "TIMERS_LAYOUT_CONF_PATH", str(conf))
    layout = ingame_menu._read_timers_layout()
    assert layout["spell"]["color"] == "none"


def test_popup_reader_accepts_none_uppercase(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), "NONE")
    monkeypatch.setattr(ingame_menu, "TIMERS_LAYOUT_CONF_PATH", str(conf))
    layout = ingame_menu._read_timers_layout()
    assert layout["spell"]["color"] == "none"
