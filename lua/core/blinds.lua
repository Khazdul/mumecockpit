-- Blinds tracker: tracks blinded targets with fixed 90 s timers.
-- Two decoupled layers:
--   1. Inbound "<name> seems to be blinded!" creates a bar (always works).
--   2. Outgoing cast snoop supplies the numeric prefix ("2.orc"); best-effort.
-- The prefix FIFO lives in the shared spellcast queue (lua/core/spellcast.lua),
-- which MUME's serialised spellcasting keeps in success/failure order.
--
-- Session-only — not persisted; wiped on char_reset by the standard
-- char_state.lua non-function-key sweep.

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
