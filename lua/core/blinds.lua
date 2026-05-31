-- Blinds tracker: tracks blinded targets with fixed 90 s timers.
-- Two decoupled layers:
--   1. Inbound "<name> seems to be blinded!" creates a bar (always works).
--   2. Outgoing cast snoop supplies the numeric prefix ("2.orc"); best-effort.
-- The prefix FIFO lives in the shared spellcast queue (lua/core/spellcast.lua),
-- which MUME's serialised spellcasting keeps in success/failure order.
--
-- Persisted per character (data/characters/<char>/blinds_active.json), mirroring
-- stored_spells.lua: written atomically on landing and on tick-prune, reloaded
-- on gmcp_char_name (cold start and reconnect) with expired entries pruned. The
-- in-memory list is still wiped on char_reset by the standard char_state.lua
-- non-function-key sweep, but the disk file is the cross-session survivor and is
-- never touched on disconnect.

local json = require("dkjson")

local BLIND_DURATION = 90

state.char.blinds = {}

-- Pending blindness casts live in the shared spellcast FIFO (lua/core/
-- spellcast.lua), tagged kind = "blindness" with a `prefix` field. spellcast
-- owns the shared failure lines and the idle flush; this module only enqueues
-- on snoop and pops on the landed-blindness line.

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function _is_cast_prefix(token)
    if not token or token == "" then return false end
    local lower = token:lower()
    if #lower > 4 then return false end
    return ("cast"):sub(1, #lower) == lower
end

local function _is_blindness_prefix(spell)
    if not spell or spell == "" then return false end
    local lower = spell:lower()
    if #lower < 3 then return false end
    return ("blindness"):sub(1, #lower) == lower
end

local function _parse_blindness_cast(raw)
    local first, rest = raw:match("^(%S+)%s+(.*)$")
    if not first or not rest then return nil end
    if not _is_cast_prefix(first) then return nil end
    local spell, tail = rest:match("^.-'([^']+)'%s*(.*)$")
    if not spell then return nil end
    if not _is_blindness_prefix(spell) then return nil end
    local num_prefix = (tail or ""):match("^(%d+%.)")
    if num_prefix then return num_prefix end
    return false
end

-- Strip a leading "An " or "A " article only when followed by whitespace, so
-- player names like "Anaru" or "Aragorn" are left intact.
local function _strip_article(name)
    local rest = name:match("^An%s+(.+)$")
    if rest then return rest end
    rest = name:match("^A%s+(.+)$")
    if rest then return rest end
    return name
end

-- ---------------------------------------------------------------------------
-- Persistence — active list (mirror lua/core/stored_spells.lua)
-- ---------------------------------------------------------------------------

local function _char_dir(name)
    return os.getenv("HOME") .. "/MUME/data/characters/" .. name .. "/"
end

-- Atomic temp-file + os.rename write of state.char.blinds. An empty list is
-- written as [] (not deleted), so reconnect always finds a definitive file.
local function _save_active()
    local name = state.char.name
    if not name then return end
    local dir  = _char_dir(name)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "blinds_active.json"
    local tmp  = path .. ".tmp"
    local encoded
    if #state.char.blinds == 0 then
        encoded = "[]"
    else
        local ok, enc = pcall(json.encode, state.char.blinds)
        if not ok then
            dbg("[BLINDS] active encode failed: " .. tostring(enc))
            return
        end
        encoded = enc
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[BLINDS] active open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

-- Reload persisted blinds on login, dropping any whose 90 s elapsed during
-- downtime. No name validation — blind names are mob names, not a canonical
-- table. Arms the tick if anything survived and always emits blinds_changed so
-- the timers pane re-serialises regardless of module load order.
local function _load_active(char_name)
    local dir  = _char_dir(char_name)
    local path = dir .. "blinds_active.json"
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[BLINDS] active load failed for " .. char_name)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    for _, e in ipairs(loaded) do
        if e.expires_at and e.expires_at <= now then
            expired = expired + 1
        else
            state.char.blinds[#state.char.blinds + 1] = e
            restored = restored + 1
        end
    end
    if #state.char.blinds > 0 then
        session_cmd("#delay {blinds_tick} {#lua {_blinds_tick()}} {2}")
    end
    dbg("[BLINDS] restored " .. restored .. " (" .. expired .. " expired)")
    events.emit("blinds_changed")
end

-- ---------------------------------------------------------------------------
-- Tick (global — called from #delay body in GAME_SESSION)
-- ---------------------------------------------------------------------------

function _blinds_tick()
    local t = state.char.blinds
    if not t then return end
    local now    = os.time()
    local pruned = false
    for i = #t, 1, -1 do
        if t[i].expires_at and t[i].expires_at <= now then
            local dropped = t[i].name
            table.remove(t, i)
            pruned = true
            char_ui("blind", dropped, "down")
        end
    end
    if #t > 0 then
        session_cmd("#delay {blinds_tick} {#lua {_blinds_tick()}} {2}")
    end
    if pruned then
        _save_active()
        events.emit("blinds_changed")
    end
end

-- ---------------------------------------------------------------------------
-- Layer 2 — outgoing cast snoop
-- ---------------------------------------------------------------------------

events.subscribe("user_input", function(raw)
    local num = _parse_blindness_cast(raw)
    if num == nil then return end
    spellcast.enqueue({ kind = "blindness", prefix = num })
    dbg("[BLINDS] cast queued: " .. tostring(num))
end)

-- Empty-input cast-abort and the shared failure lines drain the front entry
-- via spellcast (spellcast.fail_front, subscribed there). This module no
-- longer subscribes to user_input_empty.

-- ---------------------------------------------------------------------------
-- Layer 1 — landed-blindness action handler (called from tt++ #action)
-- ---------------------------------------------------------------------------

function _blinds_on_blinded(raw_name)
    if not raw_name or raw_name == "" then return end
    local name = _strip_article(raw_name)
    local e    = spellcast.pop_if_front_kind("blindness")
    local num  = e and e.prefix or false
    local now  = os.time()
    local entry = {
        name              = (num or "") .. name,
        started_at        = now,
        expected_duration = BLIND_DURATION,
        expires_at        = now + BLIND_DURATION,
    }
    state.char.blinds[#state.char.blinds + 1] = entry
    _save_active()
    -- Named delay replaces, so re-arming is idempotent.
    session_cmd("#delay {blinds_tick} {#lua {_blinds_tick()}} {2}")
    dbg("[BLINDS] landed: " .. entry.name)
    events.emit("blinds_changed")
    char_ui("blind", entry.name, "up")
end

-- ---------------------------------------------------------------------------
-- Event subscriptions — registered at load time
-- ---------------------------------------------------------------------------

events.subscribe("gmcp_char_name", function()
    state.char.blinds = {}
    if state.char.name then _load_active(state.char.name) end
end)

events.subscribe("char_reset", function()
    if GAME_SESSION then
        session_cmd("#undelay {blinds_tick}")
    end
end)

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/blinds.tin alias)
-- ---------------------------------------------------------------------------

function _register_blinds_actions()
    session_cmd([[#action {^%1 seems to be blinded!$} {#lua {_blinds_on_blinded("%1")}} {3}]])

    -- The eight shared failure lines and "Nobody here by that name." are
    -- registered once by spellcast (→ spell_cast_failed / spellcast.fail_front).
    -- Only the blindness-specific failure is owned here; it drains the shared
    -- FIFO front directly.
    session_cmd('#action {^Your victim is already blind.$} {#lua {spellcast.fail_front()}} {3}')
end

dbg("[BLINDS] loaded")
