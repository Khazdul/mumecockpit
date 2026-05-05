-- Stored spells tracker: detects cast/store commands from SENT OUTPUT, tracks
-- pending attempts in a FIFO queue, persists active stored spells and learned
-- durations per character. No rendering — buffs pane integration follows.
--
-- Load order: spells_data.lua loaded explicitly via dofile() below.
-- _install_hooks and _register_stored_spells_actions follow the same
-- lazy-registration pattern as affects.lua.

local json        = require("dkjson")
local spells_data = dofile(os.getenv("HOME") .. "/MUME/lua/core/spells_data.lua")

local TIMES_DIR  = os.getenv("HOME") .. "/MUME/logs/stored_spells_times/"
local ACTIVE_DIR = os.getenv("HOME") .. "/MUME/logs/stored_spells_active/"

state.char.stored_spells      = {}
state.char.stored_spell_times = {}

local _pending_attempts = {}  -- FIFO queue of pending store attempts
local _last_cast_intent = nil -- most recent non-store spell cast

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function _fmt_mmss(seconds)
    seconds = math.max(0, math.floor(seconds))
    return string.format("%d:%02d", math.floor(seconds / 60), seconds % 60)
end

local function _resolve_spell(s)
    if not s or s == "" then return nil end
    local lower = string.lower(s)
    local result = nil
    for full, data in pairs(spells_data.spells) do
        if lower:sub(1, #data.shortest) == data.shortest and
           full:sub(1, #lower) == lower then
            if result then return nil end
            result = full
        end
    end
    return result
end

-- ---------------------------------------------------------------------------
-- Persistence
-- ---------------------------------------------------------------------------

local function _save_times()
    local name = state.char.name
    if not name then return end
    os.execute("mkdir -p '" .. TIMES_DIR .. "'")
    local path = TIMES_DIR .. name .. ".json"
    local tmp  = path .. ".tmp"
    local ok, encoded = pcall(json.encode, state.char.stored_spell_times)
    if not ok then
        dbg("[STORED_SPELLS] encode times failed: " .. tostring(encoded))
        return
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[STORED_SPELLS] open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

local function _save_active()
    local name = state.char.name
    if not name then return end
    os.execute("mkdir -p '" .. ACTIVE_DIR .. "'")
    local path = ACTIVE_DIR .. name .. ".json"
    local tmp  = path .. ".tmp"
    local ok, encoded = pcall(json.encode, state.char.stored_spells)
    if not ok then
        dbg("[STORED_SPELLS] active encode failed: " .. tostring(encoded))
        return
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[STORED_SPELLS] active open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

local function _load_times(char_name)
    local path = TIMES_DIR .. char_name .. ".json"
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if ok and type(loaded) == "table" then
        local cleaned = {}
        local skipped = 0
        for k, v in pairs(loaded) do
            if spells_data.spells[k] then
                cleaned[k] = v
            else
                skipped = skipped + 1
            end
        end
        state.char.stored_spell_times = cleaned
        if skipped > 0 then
            dbg("[STORED_SPELLS] load times: skipped " .. skipped .. " stale entries")
        end
    else
        state.char.stored_spell_times = {}
        dbg("[STORED_SPELLS] stored_spell_times load failed for " .. char_name)
    end
end

local function _load_active(char_name)
    local path = ACTIVE_DIR .. char_name .. ".json"
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[STORED_SPELLS] active load failed for " .. char_name)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    local stale    = 0
    for _, e in ipairs(loaded) do
        if not spells_data.spells[e.name] then
            stale = stale + 1
        elseif e.tracked and e.expires_at and e.expires_at <= now then
            expired = expired + 1
        else
            state.char.stored_spells[#state.char.stored_spells + 1] = e
            restored = restored + 1
        end
    end
    dbg("[STORED_SPELLS] restored " .. restored .. " (" .. expired .. " expired, " .. stale .. " stale)")
    events.emit("stored_spells_changed")
end

-- ---------------------------------------------------------------------------
-- Event: user_cast — MUME bracketed echo (alias-coverage for _last_cast_intent)
-- ---------------------------------------------------------------------------

events.subscribe("user_cast", function(spell_text)
    local full = _resolve_spell(spell_text)
    if not full then
        dbg("[STORED_SPELLS] echo: unresolved '" .. spell_text .. "'")
        return
    end
    -- Skip store — store-attempts are populated by the SENT OUTPUT snooper,
    -- which also sees the target spell that the bracketed echo omits.
    if full == "store" then return end
    _last_cast_intent = full
    dbg("[STORED_SPELLS] echo intent: " .. full)
end)

-- ---------------------------------------------------------------------------
-- Event: user_input — parse outgoing cast commands
-- ---------------------------------------------------------------------------

events.subscribe("user_input", function(raw)
    -- MUME top-level store shortcuts: sto / stor / store <target>.
    -- Try longest prefix first to avoid mis-binding on substrings.
    for _, prefix in ipairs({ "store", "stor", "sto" }) do
        local target_text = raw:match("^" .. prefix .. "%s+(%S.*)$")
        if target_text then
            local target_full = _resolve_spell(target_text)
            if target_full then
                events.emit("store_attempt_started", target_full)
            else
                dbg("[STORED_SPELLS] attempt: unresolved target '" .. target_text .. "' (top-level)")
            end
            return
        end
    end

    local spell_text, tail
    spell_text, tail = raw:match("^c%w+%s+%w+%s+'([^']+)'%s*(.*)$")
    if not spell_text then
        spell_text, tail = raw:match("^c%w+%s+'([^']+)'%s*(.*)$")
    end
    if not spell_text then return end

    local resolved = _resolve_spell(spell_text)
    if not resolved then
        dbg("[STORED_SPELLS] user_input: no resolve for '" .. spell_text .. "'")
        return
    end

    if resolved == "store" then
        local target_text = (tail or ""):gsub("^%s+", "")
        local target = _resolve_spell(target_text)
        if target then
            events.emit("store_attempt_started", target)
        else
            dbg("[STORED_SPELLS] user_input: target no resolve '" .. tostring(target_text) .. "'")
        end
    else
        _last_cast_intent = resolved
    end
end)

-- ---------------------------------------------------------------------------
-- Event handlers
-- ---------------------------------------------------------------------------

events.subscribe("store_attempt_started", function(spell_full)
    _pending_attempts[#_pending_attempts + 1] = spell_full
    dbg("[STORED_SPELLS] attempt: " .. spell_full)
end)

events.subscribe("store_attempt_failed", function()
    if #_pending_attempts == 0 then
        dbg("[STORED_SPELLS] fail: queue empty (out of sync)")
        return
    end
    local name = table.remove(_pending_attempts, 1)
    script_ui("STORE", "cast attempt for " .. ui_var(name) .. " failed.")
end)

events.subscribe("user_input_empty", function()
    if #_pending_attempts > 0 then
        dbg("[STORED_SPELLS] aborted: empty input")
        events.emit("store_attempt_failed")
    end
end)

events.subscribe("store_succeeded", function()
    if #_pending_attempts == 0 then
        dbg("[STORED_SPELLS] stored: queue empty (out of sync)")
        return
    end
    local name = table.remove(_pending_attempts, 1)
    local samples = state.char.stored_spell_times[name] or {}
    local expected_duration
    if #samples > 0 then
        local sum = 0
        for _, v in ipairs(samples) do sum = sum + v end
        expected_duration = math.floor(sum / #samples + 0.5)
    else
        expected_duration = 5400
    end
    local now = os.time()
    local entry = {
        name              = name,
        started_at        = now,
        expected_duration = expected_duration,
        expires_at        = now + expected_duration,
        tracked           = true,
    }
    state.char.stored_spells[#state.char.stored_spells + 1] = entry
    _save_active()
    events.emit("stored_spells_changed")
    script_ui("STORE", "stored " .. ui_var(name) .. ".")
    dbg("[STORED_SPELLS] stored: " .. name)
end)

events.subscribe("store_recalled", function()
    if not _last_cast_intent then
        dbg("[STORED_SPELLS] recall: no last cast intent")
        return
    end
    local name = _last_cast_intent
    local best_idx = nil
    local best_started_at = -1
    for i, e in ipairs(state.char.stored_spells) do
        if e.name == name and e.started_at > best_started_at then
            best_started_at = e.started_at
            best_idx = i
        end
    end
    if not best_idx then
        dbg("[STORED_SPELLS] recall: no active entry for " .. name)
        return
    end
    table.remove(state.char.stored_spells, best_idx)
    _save_active()
    events.emit("stored_spells_changed")
    script_ui("STORE", ui_var(name) .. " recalled.")
    dbg("[STORED_SPELLS] recall: " .. name)
    -- _last_cast_intent is intentionally NOT cleared here
end)

events.subscribe("store_decayed", function()
    if #state.char.stored_spells == 0 then
        dbg("[STORED_SPELLS] decay: no active stored spells")
        return
    end
    local oldest_idx = 1
    for i = 2, #state.char.stored_spells do
        if state.char.stored_spells[i].started_at < state.char.stored_spells[oldest_idx].started_at then
            oldest_idx = i
        end
    end
    local entry = state.char.stored_spells[oldest_idx]
    local name  = entry.name
    if entry.tracked then
        local observed = os.time() - entry.started_at
        local times = state.char.stored_spell_times
        if not times[name] then times[name] = {} end
        local arr = times[name]
        arr[#arr + 1] = observed
        if #arr > 3 then table.remove(arr, 1) end
        _save_times()
        table.remove(state.char.stored_spells, oldest_idx)
        _save_active()
        script_ui("STORE", ui_var(name) .. " decayed (" .. _fmt_mmss(observed) .. " \xe2\x80\x94 sample recorded).")
        dbg("[STORED_SPELLS] decay: " .. name .. " observed=" .. observed)
    else
        table.remove(state.char.stored_spells, oldest_idx)
        _save_active()
        script_ui("STORE", ui_var(name) .. " decayed (untracked).")
        dbg("[STORED_SPELLS] decay: " .. name .. " untracked")
    end
    events.emit("stored_spells_changed")
end)

events.subscribe("stored_spells_untracked", function()
    if #state.char.stored_spells == 0 then return end
    local count = #state.char.stored_spells
    for _, e in ipairs(state.char.stored_spells) do
        e.tracked    = false
        e.expires_at = nil
    end
    _save_active()
    events.emit("stored_spells_changed")
    ui_warn("STORE: lost track of stored spells.")
    dbg("[STORED_SPELLS] untracked: " .. count .. " entries")
end)

-- ---------------------------------------------------------------------------
-- Hook installation (called once per load cycle from _register_stored_spells_actions)
-- ---------------------------------------------------------------------------

local _installed = false  -- reset to false on each cp -r (fresh module load)

local function _install_hooks()
    if _installed then return end
    _installed = true

    local _orig_name = gmcp.handlers["Char.Name"]
    gmcp.handlers["Char.Name"] = function(body)
        if _orig_name then _orig_name(body) end
        state.char.stored_spells      = {}
        state.char.stored_spell_times = {}
        if state.char.name then
            _load_times(state.char.name)
            _load_active(state.char.name)
        end
    end
end

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/stored_spells.tin alias)
-- ---------------------------------------------------------------------------

function _register_stored_spells_actions()
    _install_hooks()

    -- Register the SENT OUTPUT snooper in GAME_SESSION only. A top-level
    -- #event {SENT OUTPUT} would also fire on writes to the lua #run
    -- subprocess stdin (every #lua {...} call), creating a self-amplifying
    -- recursion that floods tt++ within seconds. Scoping to GAME_SESSION
    -- restricts the event to MUD-bound bytes.
    session_cmd([[#event {SENT OUTPUT} {#if {"%0" != ""} {#lua {USER_INPUT:%0}}}]])

    -- Empty-input abort detection. RECEIVED INPUT fires only on actual
    -- user input (unlike SENT OUTPUT, which also fires on tt++ IAC/GMCP
    -- flushes), so an empty %0 here is unambiguously "user pressed Enter
    -- on an empty line" — which MUME interprets as a cast abort.
    session_cmd([[#event {RECEIVED INPUT} {#if {"%0" == ""} {#lua {EMPTY_INPUT}}}]])

    local failure_patterns = {
        "^Alas, not enough mana flows through you...$",
        "^Your spell backfired!$",
        "^Nothing seems to happen.$",
        "^In your dreams, or what?$",
        "^Nah... You feel too relaxed to do that.$",
        "^Argh! You cannot concentrate any more...$",
        "^You flee %1.$",
        "^You are too afraid.$",
        "^Your mind is too full to store it.$",
        "^You failed.$",
        "^You do not know any such a spell.$",
        "^You can cast quickly, fast, normally, carefully, or thoroughly.$",
    }
    for _, pat in ipairs(failure_patterns) do
        session_cmd(string.format('#action {%s} {#lua {events.emit("store_attempt_failed")}} {3}', pat))
    end

    session_cmd('#action {^You stored it.$} {#lua {events.emit("store_succeeded")}} {3}')
    session_cmd('#action {^Your mind feels empty for a while.$} {#lua {events.emit("store_decayed")}} {3}')
    session_cmd('#action {^You quickly recall your stored spell...$} {#lua {events.emit("store_recalled")}} {3}')
    session_cmd('#action {^You blast the area with magical energies.$} {#lua {events.emit("stored_spells_untracked")}} {3}')
    session_cmd('#action {^%1 blasts the area with magical energies.$} {#lua {events.emit("stored_spells_untracked")}} {3}')

    -- MUME echoes every cast as a bracketed line regardless of whether the
    -- player typed full cast syntax or a server-side alias (e.g. arm, fireb).
    -- Two forms: [cast 'spell']  and  [cast n 'spell']  (with speed prefix).
    session_cmd([[#action {^[c%1 '%2'} {#lua {events.emit("user_cast", "%2")}} {3}]])
    session_cmd([[#action {^[c%1 %2 '%3'} {#lua {events.emit("user_cast", "%3")}} {3}]])
end

dbg("[STORED_SPELLS] loaded")
