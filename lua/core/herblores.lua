-- Herblore tracker: manually-tracked, timed phase machines. A herblore is a
-- fixed sequence of phases; each phase is a buff or debuff with its own
-- duration. When a phase's time elapses the tracker advances to the next phase;
-- the current phase renders in the timers pane exactly like an ordinary affect
-- (buff cell while type=="buff", debuff cell while type=="debuff"), moving
-- between groups by itself when a phase flips type.
--
-- Mirrors the charm tracker (lua/core/charm.lua) in shape — atomic per-character
-- JSON persistence, a named #delay tick, restore on gmcp_char_name, undelay on
-- char_reset, and a _register_*_actions registration seam — but there is no cast
-- snoop or in-flight gate: herblores are added and removed entirely by hand
-- (PR 1 via the _cp_herblore_add / _cp_herblore_remove aliases; PR 2 via the
-- click-driven add-view).
--
-- Persisted per character (data/characters/<char>/herblores_active.json):
-- only {key, started_at} is written. Everything else — the current phase index,
-- name, type, expires_at, expected_duration — is DERIVED from started_at and
-- the static catalog, so the single source of truth for "which phase is this
-- now" is _derive(), shared by the live tick and the restore path.

local json = require("dkjson")

-- ---------------------------------------------------------------------------
-- Catalog (static). Key = phase-1 base name (single token, send-keys-safe).
-- Each phase = {name, duration (s), type}. CATALOG_KEYS keeps a stable order
-- (Lua table iteration is unordered) for the timers pane's add-view in PR 2.
-- ---------------------------------------------------------------------------

local CATALOG_KEYS = { "Healing", "Travelling", "Clearthought", "Walking", "Haste" }

local CATALOG = {
    Healing = {
        { name = "Healing",       duration = 3600, type = "buff" },
        { name = "Healing (low)", duration = 3600, type = "buff" },
    },
    Travelling = {
        { name = "Travelling",       duration = 7200, type = "buff" },
        { name = "Travelling (med)", duration = 1440, type = "buff" },
        { name = "Travelling (min)", duration = 1440, type = "buff" },
    },
    Clearthought = {
        { name = "Clearthought",       duration = 120, type = "buff" },
        { name = "Clearthought (low)", duration = 240, type = "buff" },
        { name = "Clearthought (neg)", duration = 360, type = "debuff" },
    },
    Walking = {
        { name = "Walking",       duration = 1440, type = "buff" },
        { name = "Walking (med)", duration = 7200, type = "buff" },
        { name = "Walking (min)", duration = 1440, type = "buff" },
    },
    Haste = {
        { name = "Haste",            duration = 360,  type = "buff" },
        { name = "Haste (recovery)", duration = 1080, type = "debuff" },
    },
}

state.char.herblores = {}

-- The ordered catalog keys, read by lua/core/timers_state.lua to serialise the
-- static "herblore_catalog" field for PR 2's add-view. A global because core
-- files load via dofile in separate scopes and cannot require each other.
function herblore_catalog_keys()
    return CATALOG_KEYS
end

-- ---------------------------------------------------------------------------
-- Phase derivation — single source of truth for live tick and restore
-- ---------------------------------------------------------------------------

-- Walk the catalog durations from started_at. Returns
--   phase_index, name, type, expires_at, expected_duration
-- for the phase active at `now`, or nil if every phase has elapsed.
-- expires_at is the end of the current phase; expected_duration is that phase's
-- full length, so the timers pane's bar drains 100%→0% across the phase.
local function _derive(key, started_at, now)
    local phases = CATALOG[key]
    if not phases then return nil end
    local elapsed = now - started_at
    local acc = 0
    for i, p in ipairs(phases) do
        local phase_end = acc + p.duration
        if elapsed < phase_end then
            return i, p.name, p.type, started_at + phase_end, p.duration
        end
        acc = phase_end
    end
    return nil
end

-- ---------------------------------------------------------------------------
-- Persistence — active list (mirror lua/core/charm.lua)
-- ---------------------------------------------------------------------------

local function _char_dir(name)
    return os.getenv("HOME") .. "/MUME/data/characters/" .. name .. "/"
end

-- Atomic temp-file + os.rename write. Persists ONLY {key, started_at} per
-- entry; the current-phase fields are derived on load. An empty list is written
-- as [] (not deleted), so reconnect always finds a definitive file.
local function _save_active()
    local name = state.char.name
    if not name then return end
    local dir  = _char_dir(name)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "herblores_active.json"
    local tmp  = path .. ".tmp"
    local encoded
    if #state.char.herblores == 0 then
        encoded = "[]"
    else
        local persist = {}
        for _, e in ipairs(state.char.herblores) do
            persist[#persist + 1] = { key = e.key, started_at = e.started_at }
        end
        local ok, enc = pcall(json.encode, persist)
        if not ok then
            dbg("[HERB] active encode failed: " .. tostring(enc))
            return
        end
        encoded = enc
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[HERB] active open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

-- Reload persisted herblores on login. Each {key, started_at} is run through
-- _derive: dropped if every phase elapsed during downtime, otherwise rebuilt at
-- its current phase. Arms the tick if anything survived, and always emits
-- herblores_changed so the timers pane re-serialises regardless of module load
-- order (herblores.lua loads before timers_state.lua alphabetically).
local function _load_active(char_name)
    local path = _char_dir(char_name) .. "herblores_active.json"
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[HERB] active load failed for " .. char_name)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    for _, rec in ipairs(loaded) do
        if rec.key and rec.started_at then
            local phase, name, etype, expires_at, dur = _derive(rec.key, rec.started_at, now)
            if phase == nil then
                expired = expired + 1
            else
                state.char.herblores[#state.char.herblores + 1] = {
                    key               = rec.key,
                    started_at        = rec.started_at,
                    phase             = phase,
                    name              = name,
                    type              = etype,
                    expires_at        = expires_at,
                    expected_duration = dur,
                }
                restored = restored + 1
            end
        end
    end
    if restored > 0 then
        session_cmd("#delay {herblores_tick} {#lua {_herblores_tick()}} {2}")
    end
    dbg("[HERB] restored " .. restored .. " (" .. expired .. " expired)")
    events.emit("herblores_changed")
end

-- ---------------------------------------------------------------------------
-- Tick (global — called from #delay body in GAME_SESSION)
-- ---------------------------------------------------------------------------

-- Re-derive every entry. nil → the herblore fully elapsed: remove and announce
-- down. A new phase index → relabel the entry in place and announce up (the grid
-- cell relabels itself and may move between the buff and debuff groups). Every
-- live transition surfaces a UI line; only the restore path is silent. Re-arms
-- while any entry remains.
function _herblores_tick()
    local t = state.char.herblores
    if not t then return end
    local now     = os.time()
    local changed = false
    for i = #t, 1, -1 do
        local e = t[i]
        local phase, name, etype, expires_at, dur = _derive(e.key, e.started_at, now)
        if phase == nil then
            local dropped = e.name
            table.remove(t, i)
            changed = true
            char_ui("herb", dropped, "down")
        elseif phase ~= e.phase then
            e.phase             = phase
            e.name              = name
            e.type              = etype
            e.expires_at        = expires_at
            e.expected_duration = dur
            changed = true
            char_ui("herb", name, "up")
        end
    end
    if #t > 0 then
        session_cmd("#delay {herblores_tick} {#lua {_herblores_tick()}} {2}")
    end
    if changed then
        _save_active()
        events.emit("herblores_changed")
    end
end

-- ---------------------------------------------------------------------------
-- Add / remove (global — invoked by the _cp_herblore_* aliases)
-- ---------------------------------------------------------------------------

-- No-op if the key is unknown or already active (no refresh — re-adding an
-- active herblore does nothing). Otherwise start phase 1 at now, persist, arm
-- the tick, and announce up.
function herblore_add(key)
    if not CATALOG[key] then return end
    for _, e in ipairs(state.char.herblores) do
        if e.key == key then return end
    end
    local now = os.time()
    local phase, name, etype, expires_at, dur = _derive(key, now, now)
    state.char.herblores[#state.char.herblores + 1] = {
        key               = key,
        started_at        = now,
        phase             = phase,
        name              = name,
        type              = etype,
        expires_at        = expires_at,
        expected_duration = dur,
    }
    _save_active()
    -- Named delay replaces, so re-arming is idempotent.
    session_cmd("#delay {herblores_tick} {#lua {_herblores_tick()}} {2}")
    dbg("[HERB] added: " .. key)
    events.emit("herblores_changed")
    char_ui("herb", name, "up")
end

-- Remove the active herblore matching `key`. Announces down with the current
-- phase name. No-op if not active.
function herblore_remove(key)
    local t = state.char.herblores
    for i = 1, #t do
        if t[i].key == key then
            local nm = t[i].name
            table.remove(t, i)
            _save_active()
            events.emit("herblores_changed")
            char_ui("herb", nm, "down")
            return
        end
    end
end

-- ---------------------------------------------------------------------------
-- Event subscriptions — registered at load time
-- ---------------------------------------------------------------------------

events.subscribe("gmcp_char_name", function()
    state.char.herblores = {}
    if state.char.name then _load_active(state.char.name) end
end)

events.subscribe("char_reset", function()
    if GAME_SESSION then
        session_cmd("#undelay {herblores_tick}")
    end
end)

-- ---------------------------------------------------------------------------
-- Alias registration (global — called from ttpp/core/herblores.tin alias)
-- ---------------------------------------------------------------------------

-- The add/remove aliases. PR 1 exposes them for typing in the input pane to
-- exercise the backend; PR 2's add-view drives _cp_herblore_add via send-keys.
function _register_herblore_actions()
    session_cmd([[#alias {_cp_herblore_add %1}    {#lua {herblore_add("%1")}}    {3}]])
    session_cmd([[#alias {_cp_herblore_remove %1} {#lua {herblore_remove("%1")}} {3}]])
end

dbg("[HERB] loaded")
