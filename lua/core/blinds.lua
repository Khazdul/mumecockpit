-- Blinds tracker: tracks blinded targets with fixed 90 s timers.
-- Two decoupled layers:
--   1. Inbound "<name> seems to be blinded!" creates a bar (always works).
--   2. Outgoing cast snoop supplies the numeric prefix ("2.orc"); best-effort.
-- MUME serialises spellcasting, so a plain FIFO of attempt prefixes is correct.
--
-- Session-only — not persisted; wiped on char_reset by the standard
-- char_state.lua non-function-key sweep.

local BLIND_DURATION = 90

state.char.blinds = {}

-- FIFO of pending number prefixes. Each element is a string like "2." or
-- false (cast carried no explicit number). false (not nil) so #fifo works.
local _pending_blinds = {}

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
-- FIFO management
-- ---------------------------------------------------------------------------

function _blinds_queue_flush()
    _pending_blinds = {}
end

function _blinds_failure_pop()
    if #_pending_blinds > 0 then
        table.remove(_pending_blinds, 1)
    end
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
    _pending_blinds[#_pending_blinds + 1] = num
    -- Re-arm idle flush: any unconsumed prefix is dropped after 10 s.
    session_cmd("#delay {blind_que_flush} {#lua {_blinds_queue_flush()}} {10}")
    dbg("[BLINDS] cast queued: " .. tostring(num))
end)

-- MUME treats Enter on an empty line as a cast-abort; pop one queued prefix
-- so a cancelled blind cannot mis-label the next successful one. Guarded:
-- empty FIFO is a silent no-op (same shape as the failure-line pop). Does
-- NOT re-arm the idle flush — a cancel is not a cast.
events.subscribe("user_input_empty", function()
    if #_pending_blinds > 0 then
        local popped = table.remove(_pending_blinds, 1)
        dbg("[BLINDS] cast cancelled, popped: " .. tostring(popped))
    end
end)

-- ---------------------------------------------------------------------------
-- Layer 1 — landed-blindness action handler (called from tt++ #action)
-- ---------------------------------------------------------------------------

function _blinds_on_blinded(raw_name)
    if not raw_name or raw_name == "" then return end
    local name = _strip_article(raw_name)
    local num  = (#_pending_blinds > 0) and table.remove(_pending_blinds, 1) or false
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
    _pending_blinds   = {}
end)

events.subscribe("char_reset", function()
    _pending_blinds = {}
    if GAME_SESSION then
        session_cmd("#undelay {blinds_tick}")
        session_cmd("#undelay {blind_que_flush}")
    end
end)

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/blinds.tin alias)
-- ---------------------------------------------------------------------------

function _register_blinds_actions()
    session_cmd([[#action {^%1 seems to be blinded!$} {#lua {_blinds_on_blinded("%1")}} {3}]])

    local failure_patterns = {
        "^Argh! You cannot concentrate any more...$",
        "^Nah... You feel too relaxed to do that.$",
        "^In your dreams, or what?$",
        "^Alas, not enough mana flows through you...$",
        "^Your spell backfired!$",
        "^Nothing seems to happen.$",
        "^Nobody here by that name.$",
        "^You flee %1.$",
        "^You are too afraid.$",
        "^Your victim is already blind.$",
    }
    for _, pat in ipairs(failure_patterns) do
        session_cmd(string.format('#action {%s} {#lua {_blinds_failure_pop()}} {3}', pat))
    end
end

dbg("[BLINDS] loaded")
