# bridge/launcher/core_aliases.py — enumerate core-registered #alias names
# so profile_io.save_profile can filter shadowing entries before write
# (ADR 0115 follow-up; see docs/decisions/0115-core-priority-band.md).
#
# Why: priority bands stop a user trigger from outracing a core trigger at
# fire-time, but `#read`-ing a profile that contains a same-name `#alias`
# overwrites the core entry outright — priority is moot when only one
# entry remains. The profile editor is the realistic vector for an
# unintentional collision; filtering at save-time prevents 99% of the
# risk. Hand-edits and direct prompt typing remain power-user escape
# hatches per ADR 0115.
#
# Single source of truth: this module scans ttpp/main.tin and
# ttpp/core/*.tin once at launcher startup, writes the resulting set to
# bridge/runtime/core_aliases.list, and profile_io.save_profile reads
# from that file at save time. Failure to enumerate writes an empty file
# rather than crashing — empty file means "no filtering", so the save
# path fails open, not closed.
#
# Known limitation: Lua-registered script aliases (e.g. `cp -autostab`,
# `cp -autobow`) are NOT in `.tin` files under `ttpp/main.tin` or
# `ttpp/core/`, so they do not appear in the enumerated set. A user who
# hand-edits a profile to shadow a Lua-registered alias is not caught by
# this filter — that surface is small and the ADR 0115 escape-hatch
# policy still covers them.

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_io  # noqa: E402

# Runtime list location, relative to repo root.
CORE_ALIASES_LIST_REL = os.path.join("bridge", "runtime", "core_aliases.list")


def enumerate_core_aliases(repo_root):
    """Return the set of `#alias` names declared in `ttpp/main.tin` and
    every `*.tin` under `ttpp/core/`. Names are taken verbatim from
    `entry.pattern` (the first brace-arg), e.g. `"cp"`, `"cp -s"`,
    `"_register_mud_events %1"`. Multi-word and underscored internal
    names are preserved as-is — see ADR 0115 discussion.

    Re-uses `profile_io.parse_profile` to avoid a second tt++ parser.
    Files that fail to open are skipped silently; everything else is
    parsed leniently — non-alias entries are ignored.
    """
    repo_root = Path(repo_root)
    files = []
    main_tin = repo_root / "ttpp" / "main.tin"
    if main_tin.exists():
        files.append(main_tin)
    core_dir = repo_root / "ttpp" / "core"
    if core_dir.is_dir():
        files.extend(sorted(core_dir.glob("*.tin")))

    names = set()
    for path in files:
        try:
            src = path.read_text()
        except OSError:
            continue
        profile = profile_io.parse_profile(src, path)
        for item in profile.items:
            if isinstance(item, profile_io.Entry) and item.kind == "alias":
                names.add(item.pattern)
    return names


def write_core_aliases_list(repo_root, list_path=None):
    """Enumerate and write the runtime list atomically (temp + rename).
    One name per line, sorted, LF-terminated.

    On enumeration failure (or empty result), writes an empty file and
    emits a stderr warning. Empty file means `save_profile` performs no
    filtering — fail open, not closed.

    Returns the path that was written.
    """
    repo_root = Path(repo_root)
    if list_path is None:
        list_path = repo_root / CORE_ALIASES_LIST_REL
    list_path = Path(list_path)

    try:
        names = enumerate_core_aliases(repo_root)
    except Exception as exc:  # noqa: BLE001 — fail-open guard
        sys.stderr.write(
            f"[core_aliases] enumeration failed: {exc}; "
            f"writing empty list (filter inactive)\n")
        names = set()
    if not names:
        sys.stderr.write(
            "[core_aliases] empty core alias set; filter will not apply\n")

    list_path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(n + "\n" for n in sorted(names))
    tmp = list_path.with_name(list_path.name + ".tmp")
    with open(tmp, "w") as fh:
        fh.write(content)
    os.replace(tmp, list_path)
    return list_path


def format_dropped_message(names):
    """Format a one-line user-facing message for a non-empty list of
    dropped alias patterns. Truncates the listing to 3 names plus `…`
    when there are more. Caller is responsible for the C_YELLOW
    (warning) style."""
    n = len(names)
    if n <= 3:
        listing = ", ".join(names)
    else:
        listing = ", ".join(names[:3]) + ", …"
    word = "entry" if n == 1 else "entries"
    return f"Skipped {n} {word} that shadow core: {listing}."


if __name__ == "__main__":
    # Repo root is two levels up from bridge/launcher/.
    _repo_root = Path(__file__).resolve().parents[2]
    write_core_aliases_list(_repo_root)
