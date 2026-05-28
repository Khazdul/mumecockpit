# Run with: python -m unittest bridge.launcher.tests.test_core_aliases
#   (from PROJECT_DIR) — or `python -m unittest discover bridge/launcher/tests`.

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `import core_aliases` when run directly via the launcher's sys.path
# convention.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_aliases  # noqa: E402


class _RepoFixture:
    """Build a minimal repo tree under a tempdir: ttpp/main.tin and
    ttpp/core/*.tin. Returns the repo root Path."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "ttpp" / "core").mkdir(parents=True)
        (self.root / "bridge" / "runtime").mkdir(parents=True)

    def write_main(self, content):
        (self.root / "ttpp" / "main.tin").write_text(content)

    def write_core(self, name, content):
        (self.root / "ttpp" / "core" / name).write_text(content)


class TestEnumerate(unittest.TestCase):
    def test_returns_alias_patterns_from_main_and_core(self):
        repo = _RepoFixture()
        repo.write_main("#alias {hello} {world} {3}\n")
        repo.write_core("a.tin", "#alias {foo} {bar} {3}\n")
        repo.write_core("b.tin",
                        "#alias {cp -s} {do_save} {3}\n"
                        "#alias {bare} {body}\n")
        names = core_aliases.enumerate_core_aliases(repo.root)
        self.assertEqual(names, {"hello", "foo", "cp -s", "bare"})

    def test_only_alias_kind_is_collected(self):
        # Actions, highlights, substitutes, macros — none of these belong
        # in the set, since the filter only applies to #alias entries.
        repo = _RepoFixture()
        repo.write_main(
            "#alias {real} {body} {3}\n"
            "#action {pattern} {body} {3}\n"
            "#highlight {orc} {red}\n"
            "#substitute {x} {y}\n"
            "#macro {\\eOp} {flee}\n"
        )
        names = core_aliases.enumerate_core_aliases(repo.root)
        self.assertEqual(names, {"real"})

    def test_multiword_and_underscore_names_preserved(self):
        repo = _RepoFixture()
        repo.write_main("#alias {cp -profile-apply} {x} {3}\n")
        repo.write_core("u.tin",
                        "#alias {_register_mud_events %1} {body} {3}\n"
                        "#alias {_save_profile} {body} {3}\n")
        names = core_aliases.enumerate_core_aliases(repo.root)
        self.assertIn("cp -profile-apply", names)
        self.assertIn("_register_mud_events %1", names)
        self.assertIn("_save_profile", names)

    def test_missing_main_and_core_returns_empty(self):
        empty_root = Path(tempfile.mkdtemp())  # no ttpp/ at all
        self.assertEqual(core_aliases.enumerate_core_aliases(empty_root), set())

    def test_multiline_alias_body_collected(self):
        # tt++ allows multi-line bodies; the parser handles them. Pattern
        # extraction should still yield just the first brace-arg.
        repo = _RepoFixture()
        repo.write_core("m.tin",
                        "#alias {multi}\n"
                        "{\n"
                        "    line_one;\n"
                        "    line_two\n"
                        "} {3}\n")
        names = core_aliases.enumerate_core_aliases(repo.root)
        self.assertEqual(names, {"multi"})


class TestWriteRuntimeList(unittest.TestCase):
    def test_writes_sorted_lf_terminated(self):
        repo = _RepoFixture()
        repo.write_main(
            "#alias {zulu} {z} {3}\n"
            "#alias {alpha} {a} {3}\n"
            "#alias {mike} {m} {3}\n"
        )
        list_path = repo.root / "bridge" / "runtime" / "core_aliases.list"
        core_aliases.write_core_aliases_list(repo.root, list_path)
        content = list_path.read_text()
        self.assertEqual(content, "alpha\nmike\nzulu\n")

    def test_empty_when_no_aliases(self):
        repo = _RepoFixture()
        list_path = repo.root / "bridge" / "runtime" / "core_aliases.list"
        # Suppress the expected "empty core alias set" stderr notice.
        with contextlib.redirect_stderr(io.StringIO()):
            core_aliases.write_core_aliases_list(repo.root, list_path)
        self.assertEqual(list_path.read_text(), "")

    def test_atomic_rename_replaces_existing(self):
        repo = _RepoFixture()
        repo.write_main("#alias {one} {1} {3}\n")
        list_path = repo.root / "bridge" / "runtime" / "core_aliases.list"
        list_path.write_text("stale\nfile\n")
        core_aliases.write_core_aliases_list(repo.root, list_path)
        self.assertEqual(list_path.read_text(), "one\n")

    def test_against_real_repo_contains_expected_names(self):
        # Lightweight integration sanity: the enumerator should pick up
        # cp, cp -s, cp -e, reconnect, _save_profile from the real repo.
        # See the ADR 0115 follow-up "Done when" checklist.
        repo_root = Path(__file__).resolve().parents[3]
        names = core_aliases.enumerate_core_aliases(repo_root)
        for expected in ("cp", "cp -s", "cp -e", "reconnect", "_save_profile"):
            self.assertIn(expected, names,
                          f"core alias {expected!r} missing from enumerated set")


class TestFormatDroppedMessage(unittest.TestCase):
    def test_single_entry_singular(self):
        msg = core_aliases.format_dropped_message(["cp"])
        self.assertEqual(msg, "Skipped 1 entry that shadow core: cp.")

    def test_two_entries_plural(self):
        msg = core_aliases.format_dropped_message(["cp", "reconnect"])
        self.assertEqual(msg, "Skipped 2 entries that shadow core: cp, reconnect.")

    def test_three_entries_no_ellipsis(self):
        msg = core_aliases.format_dropped_message(["a", "b", "c"])
        self.assertEqual(msg, "Skipped 3 entries that shadow core: a, b, c.")

    def test_more_than_three_truncates_with_ellipsis(self):
        msg = core_aliases.format_dropped_message(["a", "b", "c", "d", "e"])
        self.assertEqual(msg, "Skipped 5 entries that shadow core: a, b, c, ….")


if __name__ == "__main__":
    unittest.main()
