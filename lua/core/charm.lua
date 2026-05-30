-- Charm tracker: tracks charmed mobs with a 99-minute auto-drop ceiling.
-- Mirrors the blinds tracker (lua/core/blinds.lua) in shape, but with an
-- in-flight gate instead of an unconditional landing:
--
--   The success line "<name> starts following you." is genuinely ambiguous —
--   mercenaries, pets, and group members also start following you. So charm
--   only tracks a follow when one of OUR charm casts is actually in flight at
--   the front of the shared cast queue (a self-cast that has started
--   concentrating, or a recalled stored charm). A follow with no in-flight
--   charm is some other follower and is ignored.
--
-- Pending charm casts live in the shared spellcast FIFO (lua/core/
-- spellcast.lua), tagged kind = "charm". This module enqueues on snoop, marks
-- the front in-flight on the concentration/recall signal, and pops it on the
-- follow line. spellcast owns the shared failure lines and the idle flush.
--
-- Persisted per character (data/characters/<char>/charms_active.json), mirroring
-- blinds: written atomically on landing, tick-prune, and explicit drop; reloaded
-- on gmcp_char_name (cold start and reconnect) with expired entries pruned. The
-- in-memory list is wiped on char_reset by the standard char_state.lua sweep,
-- but the disk file is the cross-session survivor and is never touched on
-- disconnect.

local json = require("dkjson")

local CHARM_CAP = 99 * 60

state.char.charms = {}

-- Monotonic id assigned per charm, used by the buffs pane's click-to-drop X to
-- target a specific entry (_cp_charm_drop <id>). Never reused within a session;
-- reload restores it past the highest persisted id.
local _next_id = 1

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function _is_cast_prefix(token)
    if not token or token == "" then return false end
    local lower = token:lower()
    if #lower > 4 then return false end
    return ("cast"):sub(1, #lower) == lower
end

-- Prefix of "charm", length >= 2 so 'ch' matches but a bare 'c' does not.
local function _is_charm_prefix(spell)
    if not spell or spell == "" then return false end
    local lower = spell:lower()
    if #lower < 2 then return false end
    return ("charm"):sub(1, #lower) == lower
end

-- Recognise an outgoing charm cast. No numeric prefix and no target extraction —
-- the target name comes from the success line. Returns true on a charm cast,
-- nil otherwise.
local function _parse_charm_cast(raw)
    local first, rest = raw:match("^(%S+)%s+(.*)$")
    if not first or not rest then return nil end
    if not _is_cast_prefix(first) then return nil end
    local spell = rest:match("^.-'([^']+)'")
    if not spell then return nil end
    if not _is_charm_prefix(spell) then return nil end
    return true
end

-- Strip a leading "An ", "A ", or "The " article only when followed by
-- whitespace, so player/mob names like "Anaru" or "Theoden" are left intact.
local function _strip_article(name)
    local rest = name:match("^An%s+(.+)$")
    if rest then return rest end
    rest = name:match("^A%s+(.+)$")
    if rest then return rest end
    rest = name:match("^The%s+(.+)$")
    if rest then return rest end
    return name
end

-- ---------------------------------------------------------------------------
-- Persistence — active list (mirror lua/core/blinds.lua)
-- ---------------------------------------------------------------------------

local function _char_dir(name)
    return os.getenv("HOME") .. "/MUME/data/characters/" .. name .. "/"
end

-- Atomic temp-file + os.rename write of state.char.charms. An empty list is
-- written as [] (not deleted), so reconnect always finds a definitive file.
local function _save_active()
    local name = state.char.name
    if not name then return end
    local dir  = _char_dir(name)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "charms_active.json"
    local tmp  = path .. ".tmp"
    local encoded
    if #state.char.charms == 0 then
        encoded = "[]"
    else
        local ok, enc = pcall(json.encode, state.char.charms)
        if not ok then
            dbg("[CHARM] active encode failed: " .. tostring(enc))
            return
        end
        encoded = enc
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[CHARM] active open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

-- Reload persisted charms on login, dropping any whose 99 min elapsed during
-- downtime. No name validation — charm names are mob names, not a canonical
-- table. Restores _next_id past the highest surviving id, arms the tick if
-- anything survived, and always emits charms_changed so the buffs pane
-- re-serialises regardless of module load order (charm.lua loads after
-- buffs_state.lua alphabetically, so this is load-bearing).
local function _load_active(char_name)
    local dir  = _char_dir(char_name)
    local path = dir .. "charms_active.json"
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[CHARM] active load failed for " .. char_name)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    local max_id   = 0
    for _, e in ipairs(loaded) do
        if e.expires_at and e.expires_at <= now then
            expired = expired + 1
        else
            state.char.charms[#state.char.charms + 1] = e
            if e.id and e.id > max_id then max_id = e.id end
            restored = restored + 1
        end
    end
    _next_id = max_id + 1
    if #state.char.charms > 0 then
        session_cmd("#delay {charms_tick} {#lua {_charms_tick()}} {2}")
    end
    dbg("[CHARM] restored " .. restored .. " (" .. expired .. " expired)")
    events.emit("charms_changed")
end

-- ---------------------------------------------------------------------------
-- Tick (global — called from #delay body in GAME_SESSION)
-- ---------------------------------------------------------------------------

function _charms_tick()
    local t = state.char.charms
    if not t then return end
    local now    = os.time()
    local pruned = false
    for i = #t, 1, -1 do
        if t[i].expires_at and t[i].expires_at <= now then
            local dropped = t[i].name
            table.remove(t, i)
            pruned = true
            char_ui("charm", dropped, "down")
        end
    end
    if #t > 0 then
        session_cmd("#delay {charms_tick} {#lua {_charms_tick()}} {2}")
    end
    if pruned then
        _save_active()
        events.emit("charms_changed")
    end
end

-- ---------------------------------------------------------------------------
-- Outgoing cast snoop + in-flight gate
-- ---------------------------------------------------------------------------

events.subscribe("user_input", function(raw)
    if not _parse_charm_cast(raw) then return end
    spellcast.enqueue({ kind = "charm" })
    dbg("[CHARM] cast queued")
end)

-- A self-cast that has begun concentrating, or a recalled stored charm, marks
-- the front charm entry in-flight — the gate that distinguishes a real charm
-- follow from a merc/pet/group follow.
events.subscribe("spell_cast_started",  function() spellcast.mark_front_inflight("charm") end)
events.subscribe("spell_cast_recalled", function() spellcast.mark_front_inflight("charm") end)

-- ---------------------------------------------------------------------------
-- Landed-charm action handler (called from tt++ #action)
-- ---------------------------------------------------------------------------

function _charm_on_followed(raw_name)
    if not raw_name or raw_name == "" then return end
    -- The gate: only an in-flight charm at the front of the queue makes this a
    -- real charm. A follow with no in-flight charm is a merc/pet/group follow.
    local e = spellcast.pop_if_front_inflight("charm")
    if not e then return end
    local name = _strip_article(raw_name)
    local now  = os.time()
    local entry = {
        id                = _next_id,
        name              = name,
        started_at        = now,
        expected_duration = CHARM_CAP,
        expires_at        = now + CHARM_CAP,
    }
    _next_id = _next_id + 1
    state.char.charms[#state.char.charms + 1] = entry
    _save_active()
    -- Named delay replaces, so re-arming is idempotent.
    session_cmd("#delay {charms_tick} {#lua {_charms_tick()}} {2}")
    dbg("[CHARM] landed: " .. entry.name)
    events.emit("charms_changed")
    char_ui("charm", entry.name, "up")
end

-- ---------------------------------------------------------------------------
-- Explicit drop (global — invoked by the pane's X via _cp_charm_drop alias)
-- ---------------------------------------------------------------------------

-- Remove our tracker entry only; nothing is sent to the game. No-op with a dbg
-- line if no entry matches the id.
function charm_drop(id)
    id = tonumber(id)
    if not id then return end
    local t = state.char.charms
    for i = 1, #t do
        if t[i].id == id then
            local name = t[i].name
            table.remove(t, i)
            _save_active()
            events.emit("charms_changed")
            char_ui("charm", name, "down")
            return
        end
    end
    dbg("[CHARM] drop: no entry for id " .. tostring(id))
end

-- ---------------------------------------------------------------------------
-- Event subscriptions — registered at load time
-- ---------------------------------------------------------------------------

events.subscribe("gmcp_char_name", function()
    state.char.charms = {}
    if state.char.name then _load_active(state.char.name) end
end)

events.subscribe("char_reset", function()
    if GAME_SESSION then
        session_cmd("#undelay {charms_tick}")
    end
end)

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/charm.tin alias)
-- ---------------------------------------------------------------------------

function _register_charm_actions()
    session_cmd([[#action {^%1 starts following you.$} {#lua {_charm_on_followed("%1")}} {3}]])

    -- The charm-specific resist failure. Cast-queue-only (not a shared store
    -- failure line), so it drains the shared FIFO front directly.
    session_cmd('#action {^%1 seems to be ruled by powers other than yours...$} {#lua {spellcast.fail_front()}} {3}')

    -- Click-to-drop alias: the buffs pane's X invokes this via tmux send-keys
    -- in Step 5; testable now by typing `_cp_charm_drop <id>` in the input pane.
    session_cmd('#alias {_cp_charm_drop %1} {#lua {charm_drop("%1")}} {3}')
end

dbg("[CHARM] loaded")
