# bridge/launcher/tests/test_timers_layout_bar.py — guards the shared contract
# that every Timers-layout reader parses the per-group timers_<type>_bar flag
# (val in {"0","1"} -> bool, default True when absent). Mirrors the three
# readers: the launcher's _parse_timers_layout, the pane's _load_layout, and
# the popup's _read_timers_layout.

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


def _write_conf(path, lines):
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


# ── launcher: _parse_timers_layout(path) ───────────────────────────────
def test_launcher_parser_bar_roundtrip(tmp_path):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_bar=0", "timers_buff_bar=1"])
    layout = launcher._parse_timers_layout(str(conf))
    assert layout["spell"]["bar"] is False
    assert layout["buff"]["bar"] is True


def test_launcher_parser_bar_default_true(tmp_path):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_enabled=1"])
    layout = launcher._parse_timers_layout(str(conf))
    assert layout["spell"]["bar"] is True


# ── pane: _load_layout() reads module-global TIMERS_LAYOUT_PATH ─────────
def test_pane_loader_bar_roundtrip(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_bar=0"])
    monkeypatch.setattr(timers_pane, "TIMERS_LAYOUT_PATH", str(conf))
    layout, _headers, _compact = timers_pane._load_layout()
    assert layout["spell"]["bar"] is False


def test_pane_loader_bar_default_true(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_enabled=1"])
    monkeypatch.setattr(timers_pane, "TIMERS_LAYOUT_PATH", str(conf))
    layout, _headers, _compact = timers_pane._load_layout()
    assert layout["spell"]["bar"] is True


# ── popup: _read_timers_layout() reads module-global conf path ──────────
def test_popup_reader_bar_roundtrip(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_bar=0"])
    monkeypatch.setattr(ingame_menu, "TIMERS_LAYOUT_CONF_PATH", str(conf))
    layout = ingame_menu._read_timers_layout()
    assert layout["spell"]["bar"] is False


def test_popup_reader_bar_default_true(tmp_path, monkeypatch):
    conf = tmp_path / "timers_layout.conf"
    _write_conf(str(conf), ["timers_spell_enabled=1"])
    monkeypatch.setattr(ingame_menu, "TIMERS_LAYOUT_CONF_PATH", str(conf))
    layout = ingame_menu._read_timers_layout()
    assert layout["spell"]["bar"] is True
