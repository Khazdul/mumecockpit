-- Affect tracker: tracks active affects per character, learns durations from
-- up to 3 observed samples, persists per character to data/characters/<name>/.
-- No alias, no metadata header — background collector only.
--
-- affects_data.lua is loaded explicitly via dofile() below.
-- gmcp_char_name and char_reset subscriptions are registered at load time;
-- _affects_register_triggers() only handles tt++ #action registration.

local json        = require("dkjson")
local affects_data = dofile(os.getenv("HOME") .. "/MUME/lua/core/affects_data.lua")

local _MUME        = os.getenv("HOME") .. "/MUME/"
local OLD_TIMES_DIR  = _MUME .. "logs/affect_times/"
local OLD_ACTIVE_DIR = _MUME .. "logs/affects_active/"

local function _char_dir(name)
    return _MUME .. "data/characters/" .. name .. "/"
end

-- Initialise state slots. state.char.reset() (char_state.lua) wipes all
-- non-function keys on disconnect, so these are cleared automatically.
state.char.affects      = {}
state.char.affect_times = {}

-- ---------------------------------------------------------------------------
-- Persistence
-- ---------------------------------------------------------------------------

local function _save()
    local name = state.char.name
    if not name then return end
    local dir  = _char_dir(name)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "affects_learned.json"
    local tmp  = path .. ".tmp"
    local ok, encoded = pcall(json.encode, state.char.affect_times)
    if not ok then
        dbg("[AFFECTS] encode failed: " .. tostring(encoded))
        return
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[AFFECTS] open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

local function _save_active()
    local name = state.char.name
    if not name then return end
    local dir  = _char_dir(name)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "affects_active.json"
    local tmp  = path .. ".tmp"
    local to_save = {}
    for _, e in ipairs(state.char.affects) do
        if e.expires_at ~= nil then
            to_save[#to_save + 1] = e
        end
    end
    local ok, encoded = pcall(json.encode, to_save)
    if not ok then
        dbg("[AFFECTS] active encode failed: " .. tostring(encoded))
        return
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[AFFECTS] active open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

local function _load_times(char_name)
    local dir  = _char_dir(char_name)
    local path = dir .. "affects_learned.json"
    -- one-time migration from logs/affect_times/
    do
        local fn = io.open(path, "r")
        if not fn then
            local old = OLD_TIMES_DIR .. char_name .. ".json"
            local fo = io.open(old, "r")
            if fo then
                fo:close()
                os.execute("mkdir -p '" .. dir .. "'")
                if os.rename(old, path) then
                    dbg("[AFFECTS] migrated: affect_times/" .. char_name)
                    os.execute("rmdir '" .. OLD_TIMES_DIR .. "' 2>/dev/null")
                end
            end
        else
            fn:close()
        end
    end
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if ok and type(loaded) == "table" then
        local cleaned = {}
        local skipped = 0
        for k, v in pairs(loaded) do
            local d = affects_data.affects[k]
            if d and d.duration then
                cleaned[k] = v
            else
                skipped = skipped + 1
            end
        end
        state.char.affect_times = cleaned
        if skipped > 0 then
            dbg("[AFFECTS] load: skipped " .. skipped .. " stale entries")
        end
    else
        state.char.affect_times = {}
        dbg("[AFFECTS] affect_times load failed for " .. char_name)
    end
end

local function _load_active(char_name)
    local dir  = _char_dir(char_name)
    local path = dir .. "affects_active.json"
    -- one-time migration from logs/affects_active/
    do
        local fn = io.open(path, "r")
        if not fn then
            local old = OLD_ACTIVE_DIR .. char_name .. ".json"
            local fo = io.open(old, "r")
            if fo then
                fo:close()
                os.execute("mkdir -p '" .. dir .. "'")
                if os.rename(old, path) then
                    dbg("[AFFECTS] migrated: affects_active/" .. char_name)
                    os.execute("rmdir '" .. OLD_ACTIVE_DIR .. "' 2>/dev/null")
                end
            end
        else
            fn:close()
        end
    end
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[AFFECTS] active load failed for " .. char_name)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    for _, e in ipairs(loaded) do
        if e.expires_at == nil then
            -- indefinite / corrupt — never written by current code
        elseif not affects_data.affects[e.name] or not affects_data.affects[e.name].duration then
            -- data-table changed under us
        elseif e.expires_at <= now then
            expired = expired + 1
        else
            state.char.affects[#state.char.affects + 1] = e
            restored = restored + 1
        end
    end
    if #state.char.affects > 0 then
        session_cmd("#delay {affects_tick} {#lua {_affects_tick()}} {10}")
        events.emit("affects_changed")
    end
    dbg("[AFFECTS] restored " .. restored .. " active affects (" .. expired .. " expired)")
end

-- ---------------------------------------------------------------------------
-- Duration estimation
-- ---------------------------------------------------------------------------

local function _expected_duration(name, data)
    if not data.duration then return nil end
    local times = state.char.affect_times[name]
    if times and #times >= 1 then
        local sum = 0
        for _, t in ipairs(times) do sum = sum + t end
        return math.floor(sum / #times)
    end
    return data.duration
end

-- ---------------------------------------------------------------------------
-- Tick (global — called from #delay body in GAME_SESSION)
-- ---------------------------------------------------------------------------

function _affects_tick()
    local t = state.char.affects
    if not t then return end
    local now    = os.time()
    local pruned = false
    for i = #t, 1, -1 do
        local e = t[i]
        if e.expires_at and e.expires_at <= now then
            local data = affects_data.affects[e.name]
            if not data then
                -- corrupt / removed from data table
                dbg("[AFFECTS] tick expire: " .. e.name)
                table.remove(t, i)
                pruned = true
            elseif data.dropString_1 or data.dropString_2 then
                -- drop string present: only the drop message may expire this entry;
                -- tick acts solely as a 2.5× safety net (silent, no sample)
                if now - e.started_at >= math.floor(2.5 * e.expected_duration) then
                    dbg("[AFFECTS] tick timeout (no drop): " .. e.name)
                    table.remove(t, i)
                    pruned = true
                end
                -- else: overrun — keep entry, let affect_down fire normally
            else
                -- no drop string: prune at expires_at as before
                dbg("[AFFECTS] tick expire: " .. e.name)
                table.remove(t, i)
                pruned = true
            end
        end
    end
    if #t > 0 then
        session_cmd("#delay {affects_tick} {#lua {_affects_tick()}} {10}")
    end
    events.emit("affects_changed")
    if pruned then _save_active() end
end

-- ---------------------------------------------------------------------------
-- Event handlers
-- ---------------------------------------------------------------------------

local function _find(name)
    local t = state.char.affects
    if not t then return nil, nil end
    for i, e in ipairs(t) do
        if e.name == name then return e, i end
    end
    return nil, nil
end

events.subscribe("affect_init", function(name)
    local entry = affects_data.affects[name]
    if not entry then
        dbg("[AFFECTS] init: unknown affect '" .. name .. "'")
        return
    end
    local existing = _find(name)
    if existing then
        events.emit("affect_refresh", name)
        return
    end
    local dur = _expected_duration(name, entry)
    local now = os.time()
    local rec = {
        name              = name,
        type              = entry.type,
        started_at        = now,
        expected_duration = dur,
        expires_at        = dur and (now + dur) or nil,
    }
    local t = state.char.affects
    t[#t + 1] = rec
    if #t == 1 then
        session_cmd("#delay {affects_tick} {#lua {_affects_tick()}} {10}")
    end
    dbg("[AFFECTS] init: " .. name)
    events.emit("affects_changed")
    char_ui(entry.type, name, "up")
    _save_active()
end)

events.subscribe("affect_refresh", function(name)
    local existing = _find(name)
    if not existing then
        events.emit("affect_init", name)
        return
    end
    local data = affects_data.affects[name]
    local dur = _expected_duration(name, data or {})
    local now = os.time()
    existing.started_at        = now
    existing.expected_duration = dur
    existing.expires_at        = dur and (now + dur) or nil
    dbg("[AFFECTS] refresh: " .. name)
    events.emit("affects_changed")
    if data and data.duration then
        char_ui(data.type, name, "refreshed")
    end
    _save_active()
end)

events.subscribe("affect_down", function(name)
    local existing, idx = _find(name)
    if not existing or not idx then
        dbg("[AFFECTS] down: no active entry for '" .. name .. "'")
        return
    end
    local observed = os.time() - existing.started_at
    local data = affects_data.affects[name]
    if data and data.duration then
        local times = state.char.affect_times
        if not times[name] then times[name] = {} end
        local arr = times[name]
        arr[#arr + 1] = observed
        if #arr > 3 then table.remove(arr, 1) end
        _save()
    end
    table.remove(state.char.affects, idx)
    if #state.char.affects == 0 then
        session_cmd("#undelay {affects_tick}")
    end
    dbg("[AFFECTS] down: " .. name .. " observed=" .. observed)
    events.emit("affects_changed")
    char_ui(data and data.type, name, "down")
    _save_active()
end)

-- ---------------------------------------------------------------------------
-- Event subscriptions — registered at load time
-- ---------------------------------------------------------------------------

-- Re-init affects state and load persisted data on every new character login.
-- Alphabetical load order ensures this runs before buffs_state.lua's subscriber.
events.subscribe("gmcp_char_name", function()
    state.char.affects      = {}
    state.char.affect_times = {}
    if state.char.name then
        _load_times(state.char.name)
        _load_active(state.char.name)
    end
end)

-- Cancel the tick timer when character state is wiped on disconnect.
events.subscribe("char_reset", function()
    if GAME_SESSION then
        session_cmd("#undelay {affects_tick}")
    end
end)

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/affects.tin alias)
-- ---------------------------------------------------------------------------

function _affects_register_triggers()

    -- Build pattern → [{name, ev}] map, collapsing shared trigger lines.
    local field_to_event = {
        initString_1 = "affect_init",
        initString_2 = "affect_refresh",
        dropString_1 = "affect_down",
        dropString_2 = "affect_down",
    }

    local pat_map = {}
    for affect_name, entry in pairs(affects_data.affects) do
        for field, ev in pairs(field_to_event) do
            local pat = entry[field]
            if pat then
                if not pat_map[pat] then pat_map[pat] = {} end
                local list = pat_map[pat]
                -- Deduplicate (dropString_1/2 may share a pattern for the same affect+event)
                local dup = false
                for _, p in ipairs(list) do
                    if p.name == affect_name and p.ev == ev then
                        dup = true; break
                    end
                end
                if not dup then
                    list[#list + 1] = {name = affect_name, ev = ev}
                end
            end
        end
    end

    -- Register one #action per unique converted pattern.
    for pat, pairs_list in pairs(pat_map) do
        local emits = {}
        for _, p in ipairs(pairs_list) do
            emits[#emits + 1] = string.format('events.emit("%s", "%s")', p.ev, p.name)
        end
        local body = table.concat(emits, "; ")
        session_cmd(string.format('#action {%s} {#lua {%s}} {3}', pat, body))
    end
end

dbg("[AFFECTS] loaded")
