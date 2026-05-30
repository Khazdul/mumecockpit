-- Spellcast cast-attempt owner: single registrar for the shared cast-failure
-- lines, and a runtime-only FIFO of outgoing cast attempts.
--
-- MUME serialises spellcasting, so a plain FIFO of attempt entries matches the
-- order in which the server reports success or failure. Consumers (blindness
-- today; charm later) enqueue a tagged entry when they snoop an outgoing cast
-- and pop the front when their own success line lands.
--
-- This file owns the eight failure lines that several casters share. tt++ keys
-- #action by pattern, so co-registering the same line from two modules lets the
-- later one shadow the earlier — registering each once here removes that hazard.
-- Each shared line emits the neutral `spell_cast_failed` event; consumers
-- subscribe rather than re-register.
--
-- Runtime-only — the queue is never persisted; it is wiped on login/disconnect.

-- FIFO of pending cast attempts. Each element is a table carrying at least a
-- `kind` field (e.g. { kind = "blindness", prefix = "2." }).
local _cast_queue = {}

spellcast = {}

-- ---------------------------------------------------------------------------
-- Queue management
-- ---------------------------------------------------------------------------

-- Push a tagged entry and re-arm the 10 s idle flush: any unconsumed entry is
-- dropped after 10 s of silence so a swallowed/ignored cast cannot mis-label a
-- much later success.
function spellcast.enqueue(entry)
    _cast_queue[#_cast_queue + 1] = entry
    session_cmd("#delay {spellcast_que_flush} {#lua {spellcast.clear()}} {10}")
    dbg("[SPELLCAST] queued: " .. tostring(entry and entry.kind))
end

-- Pop and return the front entry only when its kind matches; else leave the
-- queue untouched and return nil (the front belongs to another consumer).
function spellcast.pop_if_front_kind(kind)
    local front = _cast_queue[1]
    if front and front.kind == kind then
        return table.remove(_cast_queue, 1)
    end
    return nil
end

-- Drop the front entry unconditionally. Guarded: an empty queue is a silent
-- no-op. No event emitted.
function spellcast.fail_front()
    if #_cast_queue > 0 then
        local popped = table.remove(_cast_queue, 1)
        dbg("[SPELLCAST] failed front: " .. tostring(popped and popped.kind))
    end
end

-- Empty the queue and disarm the idle flush. Used on login/disconnect.
function spellcast.clear()
    _cast_queue = {}
    session_cmd("#undelay {spellcast_que_flush}")
end

-- ---------------------------------------------------------------------------
-- Event subscriptions — registered at load time
-- ---------------------------------------------------------------------------

-- MUME treats Enter on an empty line as a cast-abort, and any shared failure
-- line means the front cast did not land — both drop the front entry.
events.subscribe("user_input_empty", function() spellcast.fail_front() end)
events.subscribe("spell_cast_failed", function() spellcast.fail_front() end)

-- Wipe the queue on character switch and disconnect.
events.subscribe("gmcp_char_name", function() spellcast.clear() end)
events.subscribe("char_reset",     function() spellcast.clear() end)

-- ---------------------------------------------------------------------------
-- Trigger registration (global — called from ttpp/core/spellcast.tin alias)
-- ---------------------------------------------------------------------------

function _register_spellcast_actions()
    -- The eight failure lines shared by every caster. Each emits the neutral
    -- event so blindness, stored-spells (and later charm) can subscribe.
    local failure_patterns = {
        "^Argh! You cannot concentrate any more...$",
        "^Nah... You feel too relaxed to do that.$",
        "^In your dreams, or what?$",
        "^Alas, not enough mana flows through you...$",
        "^Your spell backfired!$",
        "^Nothing seems to happen.$",
        "^You flee %1.$",
        "^You are too afraid.$",
    }
    for _, pat in ipairs(failure_patterns) do
        session_cmd(string.format('#action {%s} {#lua {events.emit("spell_cast_failed")}} {3}', pat))
    end

    -- Cast-queue-only: a bad target aborts the cast but is not a store-failure
    -- line, so it pops the front entry directly rather than emitting the shared
    -- event. Owned here so charm can reuse it without a later move.
    session_cmd('#action {^Nobody here by that name.$} {#lua {spellcast.fail_front()}} {3}')

    -- A recalled stored spell is a spell-in-flight signal, not a failure: it
    -- emits the neutral event for consumers (stored-spells today, charm later)
    -- and deliberately does NOT touch the cast queue.
    session_cmd('#action {^You quickly recall your stored spell...$} {#lua {events.emit("spell_cast_recalled")}} {3}')
end

dbg("[SPELLCAST] loaded")
