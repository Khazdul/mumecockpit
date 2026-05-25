-- Stat / info block parser: when the player types `stat` or `info`, MUME
-- prints an "Affected by:" (or "You are subjected to the following
-- temporary effects:") block — each active affect on its own line as
-- "- <name>" — terminated by the next line that does not start with "- ".
-- Stored spells are interleaved with affects as "- stored spell <name>"
-- (literal prefix; duplicates appear as multiple lines). This module emits
-- `affects_observed` with the affect names and `stored_spells_observed`
-- with the stored-spell names (prefix stripped); the affect tracker and
-- stored-spell tracker reconcile their state from there.
--
-- No alias, no register_script — background trigger registration only.
-- Synchrony: the header trigger registers the dynamic catch-all inline in
-- its tt++ body (NOT via Lua) so the catch-all is armed before the next
-- received line is consumed; the `#class {core} {open/close}` wrap keeps
-- the inner action out of the profile auto-save (see ADR 0049 / 0050).

local HEADER1 = "Affected by:"
local HEADER2 = "You are subjected to the following temporary effects:"
local STORED_PREFIX = "stored spell "

local _active        = false
local _affect_buffer = {}
local _stored_buffer = {}

function _stat_reconcile_start()
    _active        = true
    _affect_buffer = {}
    _stored_buffer = {}
end

local function _finish()
    local affects = _affect_buffer
    local stored  = _stored_buffer
    _affect_buffer = {}
    _stored_buffer = {}
    _active        = false
    session_cmd("#unaction {^%1$}")
    events.emit("affects_observed", affects)
    events.emit("stored_spells_observed", stored)
end

-- Catch-all action body forwards each line as "STAT_LINE:<raw>" via the
-- structured-event IPC path so lines containing quotes / parentheses do
-- not break a Lua eval. Parts are rejoined with ":" because raw lines may
-- themselves contain ":".
handlers["STAT_LINE"] = function(parts)
    if not _active then return end
    local line = table.concat(parts, ":")
    if line == HEADER1 or line == HEADER2 then return end
    local name = line:match("^%- (.+)$")
    if name then
        name = name:gsub("%s+$", "")
        if name:sub(1, #STORED_PREFIX) == STORED_PREFIX then
            local stored_name = name:sub(#STORED_PREFIX + 1)
            if stored_name ~= "" then
                _stored_buffer[#_stored_buffer + 1] = stored_name
            end
        else
            _affect_buffer[#_affect_buffer + 1] = name
        end
        return
    end
    _finish()
end

function _register_stat_reconcile_actions()
    -- `%%1` in the outer body becomes `%1` after the outer fires (one
    -- substitution pass), so the inner action is stored with pattern
    -- `^%1$` and body `#lua {STAT_LINE:%1}` — a normal whole-line capture.
    session_cmd([[#action {^Affected by:$} {#lua {_stat_reconcile_start()};#class {core} {open};#action {^%%1$} {#lua {STAT_LINE:%%1}} {3};#class {core} {close}} {3}]])
    session_cmd([[#action {^You are subjected to the following temporary effects:$} {#lua {_stat_reconcile_start()};#class {core} {open};#action {^%%1$} {#lua {STAT_LINE:%%1}} {3};#class {core} {close}} {3}]])
end

dbg("[STAT_RECONCILE] loaded")
