# bridge/launcher/group_options.py — shared Group display-option controls.
#
# Pure module (no prompt_toolkit, no global state). Imported by both
# launcher.py (Options → Panes → Group) and ingame_menu.py (popup Options →
# Panes → Group) to render the two display controls and to interpret the two
# startup.conf keys that back them:
#
#   group_show_players — "1" (default) / "0"
#   group_npc_mode     — "labeled" (default) / "off".  "all" is reserved for a
#                        later step and is NOT yet a cycle stop; any unknown
#                        value normalises to "labeled".
#
# Modelled on comm_channels.py / timers_layout_grid.py. The key NAMES are
# deliberately restated in bridge/panes/group_pane.py (which must not import
# this module — bridge/launcher and bridge/panes share no import path). See
# docs/decisions/0126 and docs/group-pane.md.

from menu_chrome import menu_row

__all__ = [
    "GROUP_SHOW_PLAYERS_KEY",
    "GROUP_NPC_MODE_KEY",
    "GROUP_SHOW_PLAYERS_DEFAULT",
    "GROUP_NPC_MODE_DEFAULT",
    "NPC_MODE_CYCLE",
    "NPC_MODE_LABELS",
    "PLAYERS_ROW",
    "NPC_ROW",
    "normalize_npc_mode",
    "next_npc_mode",
    "npc_mode_label",
    "parse_show_players",
    "read_group_options",
    "group_options_fragments",
]

# ── Config contract (key names restated in bridge/panes/group_pane.py) ──
GROUP_SHOW_PLAYERS_KEY = "group_show_players"
GROUP_NPC_MODE_KEY     = "group_npc_mode"

GROUP_SHOW_PLAYERS_DEFAULT = True
GROUP_NPC_MODE_DEFAULT     = "labeled"

# Cycle order for the NPC-visibility control. "all" (unlabeled group NPCs) is
# reserved for a later step and deliberately omitted, so the control has two
# stops today: Off ↔ Labeled.
NPC_MODE_CYCLE = ["off", "labeled"]

NPC_MODE_LABELS = {
    "off":     "Off",
    "labeled": "Labeled",
    "all":     "All",
}

# Row indices within the Group page (shared by both surfaces' cursor state).
PLAYERS_ROW = 0
NPC_ROW     = 1


# ── Value interpretation ────────────────────────────────────────────────
def parse_show_players(val):
    """Interpret a raw group_show_players value. ``None`` (missing key) →
    the default; otherwise only an explicit "0" reads as off."""
    if val is None:
        return GROUP_SHOW_PLAYERS_DEFAULT
    return str(val).strip() != "0"


def normalize_npc_mode(val):
    """Normalise a raw group_npc_mode value to a cycle stop. Only "off" maps
    to Off; everything else (including "labeled", the reserved "all", and any
    unknown value) maps to "labeled"."""
    if val is not None and str(val).strip() == "off":
        return "off"
    return "labeled"


def next_npc_mode(cur, delta=1):
    """Advance the NPC mode through NPC_MODE_CYCLE (wrapping)."""
    cur = normalize_npc_mode(cur)
    idx = NPC_MODE_CYCLE.index(cur)
    return NPC_MODE_CYCLE[(idx + delta) % len(NPC_MODE_CYCLE)]


def npc_mode_label(mode):
    """Display label for an NPC mode value."""
    return NPC_MODE_LABELS.get(mode, NPC_MODE_LABELS["labeled"])


def read_group_options(conf):
    """Read (show_players, npc_mode) from a parsed startup.conf dict. Missing
    keys fall through to the runtime defaults (players-on / NPC-labeled)."""
    show_players = parse_show_players(conf.get(GROUP_SHOW_PLAYERS_KEY))
    npc_mode     = normalize_npc_mode(conf.get(GROUP_NPC_MODE_KEY)) \
        if conf.get(GROUP_NPC_MODE_KEY) is not None else GROUP_NPC_MODE_DEFAULT
    return show_players, npc_mode


# ── Render ──────────────────────────────────────────────────────────────
def group_options_fragments(show_players, npc_mode, term_cols, cursor,
                            players_handler=None, npc_handler=None):
    """Fragments for the two Group display-option rows, each a centred
    ``<< label >>`` menu row.

      - Players — ``[X] Show players`` / ``[ ] Show players`` (binary toggle).
      - NPC     — ``NPC visibility: Labeled`` / ``NPC visibility: Off``
                  (cycle through NPC_MODE_CYCLE).

    ``cursor`` is the focused row (``PLAYERS_ROW`` / ``NPC_ROW``) or ``None``
    when the cursor sits outside the option block (e.g. on Back). Both
    surfaces render Back themselves, matching the Communication frame.
    """
    rows = [
        (PLAYERS_ROW,
         f"[{'X' if show_players else ' '}] Show players",
         players_handler),
        (NPC_ROW,
         f"NPC visibility: {npc_mode_label(npc_mode)}",
         npc_handler),
    ]

    frags = []
    for ri, label, handler in rows:
        state     = "selected" if cursor == ri else "inactive"
        row_w     = len(label) + 6
        left_pad  = max(0, (term_cols - row_w) // 2)
        right_pad = max(0, term_cols - left_pad - row_w)
        frags.append(("", " " * left_pad))
        frags.extend(menu_row(label, state, mouse_handler=handler))
        frags.append(("", " " * right_pad))
        frags.append(("", "\n"))
    return frags
