# Unit tests for bridge/launcher/templates/startup.conf — the shipped
# fresh-install defaults file (ADR 0101). Pins the template against
# the explicit key tuple in launcher.py's _save_conf so neither side
# can drift silently.
#
# Runs without prompt_toolkit, same pattern as test_panes_grid.py: the
# launcher module is parsed for the tuple via a regex rather than
# imported, since launcher.py refuses to load without prompt_toolkit.

import os
import re
import unittest


HERE         = os.path.dirname(os.path.abspath(__file__))
LAUNCHER_DIR = os.path.dirname(HERE)
TEMPLATE     = os.path.join(LAUNCHER_DIR, "templates", "startup.conf")
LAUNCHER_PY  = os.path.join(LAUNCHER_DIR, "launcher.py")


def _parse_template(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k:
                out[k] = v.strip()
    return out


def _save_conf_keys():
    # Pull the unconditional key tuple out of launcher.py's _save_conf
    # without importing the module (prompt_toolkit may be absent in this
    # test env). The per-pane border_<key> and the retired show_pane_dividers
    # fallback are written conditionally outside this tuple (never seeded into
    # the fresh-install template), so they are deliberately excluded here.
    with open(LAUNCHER_PY) as fh:
        src = fh.read()
    m = re.search(r"for key in \((.*?)\):", src, flags=re.S)
    assert m, "could not locate the _save_conf key tuple in launcher.py"
    body = m.group(1)
    # Each entry is a bare double-quoted string inside the tuple. Pull every
    # "key" — the same regex catches each one in order.
    return [s for s in re.findall(r'"([a-z][a-z_]+)"', body)]


class TestStartupConfTemplate(unittest.TestCase):

    def setUp(self):
        self.tpl = _parse_template(TEMPLATE)

    def test_template_has_all_save_conf_keys(self):
        save_keys = set(_save_conf_keys())
        tpl_keys  = set(self.tpl.keys())
        self.assertEqual(
            tpl_keys, save_keys,
            f"template/save_conf drift: "
            f"only in template={tpl_keys - save_keys}, "
            f"only in _save_conf={save_keys - tpl_keys}",
        )

    def test_input_autosuggest_defaults_off(self):
        # Opt-in inline history autosuggestion ships OFF on a fresh install.
        self.assertEqual(self.tpl["input_autosuggest"], "0")

    def test_show_dev_off_others_on(self):
        self.assertEqual(self.tpl["show_dev"], "0")
        for key in (
            "show_status", "show_timers", "show_group",
            "show_comm", "show_ui",
        ):
            self.assertEqual(
                self.tpl[key], "1",
                f"{key} must default to 1 in the shipped template",
            )


if __name__ == "__main__":
    unittest.main()
