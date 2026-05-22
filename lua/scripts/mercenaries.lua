-- ============================================================
--  mercenaries
-- ============================================================
-- @summary  Track hired citizen mercenaries (auto-label, timer, gold)
-- @alias    merc       Render the mercenary panel
-- @alias    mercs      Alias for `merc`
-- @help     Auto-labels each hired citizen mercenary with a random
-- @help     name from a built-in list and groups it. Tracks remaining
-- @help     contract time (24 minutes per 10 silver) and total silver paid.
-- @help
-- @help     Subcommands:
-- @help       merc           Render the framed panel
-- @help       merc autopay   Toggle auto-payment on tap (default OFF)
-- @help
-- @help     Status lines (▶ MERC) report hire, tap, payment,
-- @help     renew, expiry warnings, and removal.

-- Self-contained script. Records are keyed by label (the stable identity);
-- GMCP group membership is room-scoped, so ids are transient presence
-- handles. Records survive link loss and room exits — only the leaves/death
-- text triggers or the periodic expiry timer drop a merc. See docs/gmcp.md
-- (Group section) for the room-scope semantics.

local PANEL_W = 67
local BAR_W   = 20

-- Name pool — kept short to stay under the 33-char script_ui budget.
local NAME_POOL = {
    "Bubba", "Hank", "Cletus", "Leroy", "Billybob", "Earl", "Jeb",
    "Roscoe", "Boomer", "Buford", "Cooter", "Dwayne", "Gomer", "Junior",
    "Merle", "Otis", "Rufus", "Skeeter", "Travis", "Waylon", "Zeke",
    "Clovis", "Festus", "Hoss", "Jethro", "Lonnie", "Newt", "Pruitt",
    "Vern", "Wade", "Darryl",
}

-- tt++ 24-bit truecolor palette
local FRAME   = "<F9AA8B7>"
local TITLE   = "<FD4A04E>"
local WHITE   = "<FFFFFFF>"
local DIM     = "<F555555>"
local GREEN   = "<F0FA838>"
local OLIVE   = "<F8A7838>"
local ORANGE  = "<FFF7020>"
local RED     = "<FE02020>"
local GOLD_FG = "<FFFEE58>"
local R       = "<099>"

-- ── module state ─────────────────────────────────────────────────────────────

local M = {}
scripts.mercenaries = M

-- mercs: keyed by lower-cased name (the label — stable identity).
-- Record: { name, label_lc, gmcp_id, present, expiry, silver_paid, state,
--          warned_5min, hp_band, mp_band }
--   gmcp_id  transient; bound while the merc is in our room, nil otherwise.
--   present  true while the merc is in our room (has a bound gmcp_id).
--   state    "active" | "grace" (grace = pay due, 1-minute window).
local mercs       = {}
local id_to_label = {}   -- gmcp id → label_lc (rebuilt from group_member_added)
local autopay     = false

-- ── helpers ──────────────────────────────────────────────────────────────────

local function _dbg(msg) dbg("[MERC] " .. msg) end

-- Seeded so the first-hire name varies across sessions; default seed is constant.
math.randomseed(os.time())

local function _pick_unused_name()
    local used = {}
    for _, rec in pairs(mercs) do used[rec.name:lower()] = true end
    local unused = {}
    for _, n in ipairs(NAME_POOL) do
        if not used[n:lower()] then unused[#unused+1] = n end
    end
    if #unused == 0 then return nil end
    return unused[math.random(#unused)]
end

local function _format_time(seconds)
    if seconds < 0 then seconds = 0 end
    local m = math.floor(seconds / 60)
    local s = seconds % 60
    return string.format("%02d:%02d", m, s)
end

local function _format_silver(silver)
    local gold = math.floor(silver / 20)
    local rem  = silver % 20
    local gp = (gold == 1) and "1 gold"   or (gold .. " gold")
    local sp = (rem  == 1) and "1 silver" or (rem  .. " silver")
    if gold > 0 and rem > 0 then return gp .. ", " .. sp end
    if gold > 0              then return gp end
    return sp
end

local function _update_vitals(rec, member)
    rec.hp_band = member.hp_string or rec.hp_band
    rec.mp_band = member.mp_string or rec.mp_band
end

-- ── panel rendering ─────────────────────────────────────────────────────────
-- Visual widths assume the player's terminal renders the box-drawing chars,
-- bar cells (█/░) and ⚠ as 1 cell each. Color codes are zero-width.

local function _wrap_row(content)
    return FRAME .. "│" .. R .. content .. FRAME .. "│" .. R
end

local function _empty_row()
    return _wrap_row(string.rep(" ", PANEL_W))
end

local function _top_border()
    local title_str = "  MERCENARIES  "
    local dashes = PANEL_W - #title_str
    local left_d  = math.floor(dashes / 2)
    local right_d = dashes - left_d
    return FRAME .. "╭" .. string.rep("─", left_d) .. R
        .. TITLE .. title_str .. R
        .. FRAME .. string.rep("─", right_d) .. "╮" .. R
end

local function _divider()
    return FRAME .. "├" .. string.rep("─", PANEL_W) .. "┤" .. R
end

local function _bottom_border()
    return FRAME .. "╰" .. string.rep("─", PANEL_W) .. "╯" .. R
end

local function _name_row(rec)
    local remaining = rec.expiry - os.time()
    local time_str  = _format_time(remaining)

    local warn_seg, time_color
    if rec.state == "grace" then
        warn_seg   = RED .. "⚠ " .. R              -- 2 visual cells
        time_color = RED
    else
        warn_seg   = "  "
        time_color = rec.present and WHITE or DIM
    end

    local name_color = rec.present and WHITE or DIM
    local name_text  = rec.present and rec.name or (rec.name .. " (away)")
    local gold_str   = _format_silver(rec.silver_paid)
    local name_vlen  = #name_text    -- names are ASCII
    local gold_vlen  = #gold_str

    local s = {}
    s[#s+1] = "  "
    s[#s+1] = name_color .. name_text .. R
    s[#s+1] = string.rep(" ", 28 - name_vlen)
    s[#s+1] = warn_seg
    s[#s+1] = time_color .. "time " .. time_str .. R
    s[#s+1] = string.rep(" ", 7)
    s[#s+1] = GOLD_FG .. string.rep(" ", 17 - gold_vlen) .. gold_str .. R
    s[#s+1] = " "
    -- visual total: 2 + 28 + 2 + 10 + 7 + 17 + 1 = 67
    return _wrap_row(table.concat(s))
end

local function _bars_row(label, pct, band, default_fg, present)
    local fill
    if pct == nil then
        fill = 0
    else
        fill = math.floor(pct * BAR_W + 0.5)
        if fill < 0      then fill = 0      end
        if fill > BAR_W  then fill = BAR_W  end
    end

    local bar_fg
    if not present then
        bar_fg = DIM                              -- away: last-known, greyed
    elseif pct == nil then
        bar_fg = DIM
    elseif pct <= 0.25 then
        bar_fg = RED
    elseif pct <= 0.45 then
        bar_fg = ORANGE
    else
        bar_fg = default_fg
    end

    local bar = bar_fg .. string.rep("█", fill)
        .. DIM .. string.rep("░", BAR_W - fill) .. R

    local label_padded = label .. string.rep(" ", 7 - #label)
    local band_str  = band or ""
    local band_vlen = #band_str

    local s = {}
    s[#s+1] = "  "
    s[#s+1] = label_padded
    s[#s+1] = bar
    s[#s+1] = "  "
    s[#s+1] = DIM .. band_str .. R
    s[#s+1] = string.rep(" ", 35 - band_vlen)
    s[#s+1] = " "
    -- visual total: 2 + 7 + 20 + 2 + 35 + 1 = 67
    return _wrap_row(table.concat(s))
end

local function _footer_row(count)
    local autopay_text  = autopay and "ON" or "OFF"
    local autopay_color = autopay and GREEN or DIM
    local count_text    = (count == 1) and "1 mercenary"
        or (count .. " mercenaries")

    local left_vlen  = #"  Autopay: " + #autopay_text
    local right_vlen = #count_text
    local pad_count  = PANEL_W - left_vlen - right_vlen - 2

    local s = {}
    s[#s+1] = WHITE .. "  Autopay: " .. R
    s[#s+1] = autopay_color .. autopay_text .. R
    s[#s+1] = string.rep(" ", pad_count)
    s[#s+1] = WHITE .. count_text .. R
    s[#s+1] = "  "
    return _wrap_row(table.concat(s))
end

local function _empty_state()
    local ses = GAME_SESSION or "gts"

    local function _centered(text, color)
        local pad = math.floor((PANEL_W - #text) / 2)
        return _wrap_row(string.rep(" ", pad) .. color .. text .. R
            .. string.rep(" ", PANEL_W - pad - #text))
    end

    local function _left(text)
        return _wrap_row("   " .. WHITE .. text .. R
            .. string.rep(" ", PANEL_W - 3 - #text))
    end

    tintin_show(ses, _top_border())
    tintin_show(ses, _empty_row())
    tintin_show(ses, _centered("You have no mercenaries right now.", WHITE))
    tintin_show(ses, _empty_row())
    tintin_show(ses, _left("Hire one by giving 10 silver to a citizen mercenary:"))
    tintin_show(ses, _centered("give 10 silver mercenary", GOLD_FG))
    tintin_show(ses, _empty_row())
    tintin_show(ses, _left("A mercenary fights alongside you and follows for ~24 minutes,"))
    tintin_show(ses, _left("then asks to be paid again. This panel tracks each mercenary's"))
    tintin_show(ses, _left("HP, time remaining and total cost."))
    tintin_show(ses, _empty_row())

    -- Tip with inline highlighted command.
    local pre  = "Tip: `"
    local cmd  = "merc autopay"
    local post = "` pays your mercenaries automatically."
    local vlen = #pre + #cmd + #post
    tintin_show(ses, _wrap_row("   "
        .. WHITE .. pre .. R
        .. GOLD_FG .. cmd .. R
        .. WHITE .. post .. R
        .. string.rep(" ", PANEL_W - 3 - vlen)))

    tintin_show(ses, _empty_row())
    tintin_show(ses, _bottom_border())
end

local function _render_panel()
    if next(mercs) == nil then
        _empty_state()
        return
    end
    local ses = GAME_SESSION or "gts"

    local list = {}
    for _, rec in pairs(mercs) do list[#list+1] = rec end
    table.sort(list, function(a, b) return a.name < b.name end)

    tintin_show(ses, _top_border())
    tintin_show(ses, _empty_row())
    for _, rec in ipairs(list) do
        local hp_pct = state.group.pct_for("hp", nil, nil, rec.hp_band)
        local mp_pct = state.group.pct_for("mp", nil, nil, rec.mp_band)
        tintin_show(ses, _name_row(rec))
        tintin_show(ses, _bars_row("HP",    hp_pct, rec.hp_band, GREEN, rec.present))
        tintin_show(ses, _bars_row("Moves", mp_pct, rec.mp_band, OLIVE, rec.present))
        tintin_show(ses, _empty_row())
    end
    tintin_show(ses, _divider())
    tintin_show(ses, _footer_row(#list))
    tintin_show(ses, _bottom_border())
end

-- ── triggers ────────────────────────────────────────────────────────────────
-- Anchored so the parenthesised "(label) starts following you" variant cannot
-- match the new-hire pattern. Patterns use tt++ default glob mode where `.`
-- is literal and `%1` is a non-greedy capture.

local function _unregister_triggers()
    session_cmd("#unaction {^A citizen mercenary starts following you.$}")
    session_cmd("#unaction {^A citizen mercenary (%1) taps you on the shoulder.$}")
    session_cmd("#unaction {^A citizen mercenary (%1) says 'Thank you. I am at your service.'$}")
    session_cmd("#unaction {^A citizen mercenary (%1) leaves and goes to seek another employer.$}")
end

local function _register_triggers()
    _unregister_triggers()
    session_cmd("#action {^A citizen mercenary starts following you.$} {#lua {scripts.mercenaries.on_hire()}}")
    session_cmd("#action {^A citizen mercenary (%1) taps you on the shoulder.$} {#lua {scripts.mercenaries.on_tap(\"%1\")}}")
    session_cmd("#action {^A citizen mercenary (%1) says 'Thank you. I am at your service.'$} {#lua {scripts.mercenaries.on_renew(\"%1\")}}")
    session_cmd("#action {^A citizen mercenary (%1) leaves and goes to seek another employer.$} {#lua {scripts.mercenaries.on_leave(\"%1\")}}")
    -- TODO: the exact MUME death line for a mercenary is not yet known.
    -- Until provided, a dead merc is only removed by the periodic expiry
    -- timer (~90s past contract end). Group.Remove is room-scoped presence
    -- and never removes a record.
end

-- ── tick / reconnect ────────────────────────────────────────────────────────

local function _arm_tick()
    if next(mercs) ~= nil then
        session_cmd("#delay {merc_tick} {#lua {scripts.mercenaries._tick()}} {10}")
    end
end

function M._tick()
    local now = os.time()
    local expired = {}
    for _, rec in pairs(mercs) do
        if rec.state == "active" then
            local remaining = rec.expiry - now
            if remaining > 0 and remaining < 300 and not rec.warned_5min then
                rec.warned_5min = true
                script_ui("MERC", rec.name .. " expires soon.")
            end
        end
        -- Wall-clock anchored expiry: drops any merc whose contract ended
        -- more than ~90s ago (covers the 1-minute grace plus slack). For
        -- a present merc this is the safety net after triggers; for an
        -- away merc it is the only removal path.
        if now - rec.expiry > 90 then
            expired[#expired+1] = rec
        end
    end
    for _, rec in ipairs(expired) do
        if rec.gmcp_id then id_to_label[rec.gmcp_id] = nil end
        mercs[rec.label_lc] = nil
        script_ui("MERC", rec.name .. " expired.")
    end
    _arm_tick()
end

-- ── trigger handlers (public — called from tt++ #action bodies) ────────────

function M.on_hire()
    local name = _pick_unused_name()
    if not name then
        script_ui("MERC", "name pool exhausted.")
        _dbg("name pool exhausted; cannot label new mercenary")
        return
    end
    local label_lc = name:lower()
    mercs[label_lc] = {
        name        = name,
        label_lc    = label_lc,
        gmcp_id     = nil,
        present     = false,
        expiry      = os.time() + 25 * 60,
        silver_paid = 10,
        state       = "active",
        warned_5min = false,
        hp_band     = nil,
        mp_band     = nil,
    }
    send("label mercenary " .. name)
    send("group " .. name)
    script_ui("MERC", name .. " hired.")
    _arm_tick()
end

function M.on_tap(label)
    local label_lc = label:lower()
    local rec = mercs[label_lc]
    if not rec then return end
    rec.state  = "grace"
    rec.expiry = os.time() + 60
    script_ui("MERC", rec.name .. " taps — pay due.")
    if autopay then
        send("give 10 silver " .. label)
        script_ui("MERC", rec.name .. " paid (10s).")
    end
end

function M.on_renew(label)
    local label_lc = label:lower()
    local rec = mercs[label_lc]
    if not rec then return end
    rec.expiry      = rec.expiry + 25 * 60
    rec.silver_paid = rec.silver_paid + 10
    rec.state       = "active"
    rec.warned_5min = false
    script_ui("MERC", rec.name .. " renewed +25m.")
end

function M.on_leave(label)
    local label_lc = label:lower()
    local rec = mercs[label_lc]
    if not rec then return end
    if rec.gmcp_id then id_to_label[rec.gmcp_id] = nil end
    mercs[label_lc] = nil
    script_ui("MERC", rec.name .. " left.")
end

-- ── alias body ──────────────────────────────────────────────────────────────

function M.cmd(arg)
    if arg == nil or arg == "" then
        _render_panel()
    elseif arg == "autopay" then
        autopay = not autopay
        tintin_show(GAME_SESSION or "gts",
            FRAME .. "## MERC AUTOPAY: " .. WHITE
            .. (autopay and "ON" or "OFF") .. R)
    else
        tintin_show(GAME_SESSION or "gts",
            FRAME .. "## MERC: " .. WHITE
            .. "usage: merc [autopay]" .. R)
    end
end

-- ── GMCP subscribers ────────────────────────────────────────────────────────

-- Group.Add covers both fresh hires and mercs re-entering our room (room-scoped
-- GMCP assigns a NEW id on each arrival). Same path: bind id, mark present,
-- refresh vitals. Never creates or removes records.
events.subscribe("group_member_added", function(member)
    local mname = (member.name or ""):lower()
    if mname ~= "citizen mercenary" then return end
    local label = member.label
    if not label then return end
    local label_lc = label:lower()
    local rec = mercs[label_lc]
    if not rec then
        _dbg("ignored untracked mercenary label=" .. tostring(label))
        return
    end
    rec.gmcp_id = member.id
    rec.present = true
    id_to_label[member.id] = label_lc
    _update_vitals(rec, member)
end)

events.subscribe("group_member_updated", function(member)
    local label_lc = id_to_label[member.id]
    if not label_lc then return end
    local rec = mercs[label_lc]
    if not rec then return end
    _update_vitals(rec, member)
end)

-- Group.Remove is room-scoped: it means the merc left our room, not that the
-- contract ended. Mark away; the record persists until a text trigger or the
-- expiry timer removes it. No script_ui — silent presence change.
events.subscribe("group_member_removed", function(id)
    local label_lc = id_to_label[id]
    if not label_lc then return end
    id_to_label[id] = nil
    local rec = mercs[label_lc]
    if not rec then return end
    rec.gmcp_id = nil
    rec.present = false
    _dbg("away label=" .. rec.label_lc)
end)

-- ── session lifecycle ───────────────────────────────────────────────────────

events.subscribe("run_started", function()
    -- Records survive link loss; gmcp ids and presence do not. Incoming
    -- Group.Add events will re-bind ids by label; the periodic timer drops
    -- anything that genuinely expired while we were disconnected.
    id_to_label = {}
    for _, rec in pairs(mercs) do
        rec.gmcp_id = nil
        rec.present = false
    end
    _register_triggers()
    _arm_tick()
end)

-- ── setup ───────────────────────────────────────────────────────────────────

game_cmd('#alias {merc}  {#lua {scripts.mercenaries.cmd("%1")}}')
game_cmd('#alias {mercs} {#lua {scripts.mercenaries.cmd("%1")}}')

_dbg("loaded")
