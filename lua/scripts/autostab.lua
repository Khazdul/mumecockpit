-- ===== AUTOSTAB =====
-- Self-contained script. Registers alias on load — no paired .tin file needed.
--
-- Alias:  as<dir>  (e.g. ase = autostab east)
-- Flow:   go dir -> backstab $target -> escape retDir
--   on escape success: repeat cycle, reset watchdog
--   on escape fail:    retry escape up to 2 times per cycle, reset watchdog
--                      if both retries fail: flee + abort
--   on target dead/gone: abort
--
-- MUD triggers (success/fail/dead/gone) and watchdog (as_watch)
-- are registered dynamically by autostab_start() and cleaned up on abort.
-- Watchdog fires if no escape result is seen within WATCH_TIMEOUT seconds.

local RET           = { n="s", s="n", e="w", w="e", u="d", d="u" }
local WATCH_TIMEOUT = 10  -- seconds with no activity before auto-cancel

local as = {
    active      = false,
    dir         = nil,
    ret         = nil,
    target      = nil,
    retry_count = 0,
}

local function as_dbg(msg)
    dbg("[AUTOSTAB] " .. msg)
end

local function as_show(msg)
    tintin_show(GAME_SESSION or "gts", "<F9AA8B7>## AUTOSTAB: <FFFFFFF>" .. msg .. "<099>")
end

-- -----------------------------
-- TRIGGER LIFECYCLE
-- -----------------------------

local function register_triggers()
    session_cmd("#action {You successfully escaped the fight!} {#lua {autostab_on_success()}}")
    session_cmd("#action {You failed to escape the fight!} {#lua {autostab_on_fail()}}")
    session_cmd("#action {%1 is dead! R.I.P.} {#lua {autostab_on_dead()}}")
    session_cmd("#action {%1 disappears into nothing.} {#lua {autostab_on_gone()}}")
end

local function unregister_triggers()
    session_cmd("#unaction {You successfully escaped the fight!}")
    session_cmd("#unaction {You failed to escape the fight!}")
    session_cmd("#unaction {%1 is dead! R.I.P.}")
    session_cmd("#unaction {%1 disappears into nothing.}")
end

-- -----------------------------
-- WATCHDOG
-- Calling reset_watchdog() again replaces the existing delay (natural reset).
-- -----------------------------

local function reset_watchdog()
    session_cmd(string.format("#delay {as_watch} {#lua {autostab_watchdog()}} {%d}", WATCH_TIMEOUT))
end

-- -----------------------------
-- INTERNAL
-- -----------------------------

local function do_cycle()
    send(as.dir)
    send("backstab " .. as.target)
    send("escape "   .. as.ret)
end

local function abort(reason)
    as.active = false
    unregister_triggers()
    session_cmd("#undelay {as_watch}")
    as_dbg("stopped: " .. reason)
    script_ui("AUTOSTAB", "Stopped — " .. reason)
end

-- -----------------------------
-- PUBLIC API (called via #lua from tt++ triggers/aliases/delays)
-- -----------------------------

function autostab_start(dir, target)
    if not RET[dir] then
        as_show("bad direction: " .. tostring(dir))
        return
    end
    if not target or target == "" then
        as_show("no target set — use 'z <name>' first")
        return
    end

    -- Clean up any still-running session before starting fresh
    if as.active then
        unregister_triggers()
        session_cmd("#undelay {as_watch}")
    end

    as.active      = true
    as.dir         = dir
    as.ret         = RET[dir]
    as.target      = target
    as.retry_count = 0

    register_triggers()
    reset_watchdog()

    as_dbg(string.format("start dir=%s ret=%s target=%s", dir, as.ret, target))
    as_show(string.format("target: %s dir: %s", as.target, as.dir))
    script_ui("AUTOSTAB", "Running")
    do_cycle()
end

function autostab_on_success()
    if not as.active then return end
    as.retry_count = 0
    reset_watchdog()
    as_dbg("escaped — repeating")
    do_cycle()
end

function autostab_on_fail()
    if not as.active then return end
    as.retry_count = as.retry_count + 1
    reset_watchdog()
    if as.retry_count <= 2 then
        as_dbg(string.format("escape failed (attempt %d/2) — retrying", as.retry_count))
        send("escape " .. as.ret)
    else
        as_dbg("escape failed 3 times — fleeing and aborting")
        send("flee")
        abort("fled")
    end
end

function autostab_on_dead()
    if not as.active then return end
    abort("dead")
end

function autostab_on_gone()
    if not as.active then return end
    abort("gone")
end

function autostab_watchdog()
    if not as.active then return end
    -- Watchdog already fired — no need to #undelay, just clean up triggers
    as.active = false
    unregister_triggers()
    as_dbg(string.format("watchdog: no activity for %ds — stopped", WATCH_TIMEOUT))
    script_ui("AUTOSTAB", "Stopped — timed out")
end

-- -----------------------------
-- SETUP — register alias on load, declare metadata
-- -----------------------------
game_cmd('#alias {as%1} {#lua {autostab_start("%1", "$target")}}')
register_script({
    alias   = "autostab",
    summary = "backstab/escape loop",
    help    = {
        "Usage:  as<dir>   e.g. ase, asw, asn, asu",
        "        Set target first: z <name>",
        "",
        "Cycle:",
        "  go dir -> backstab -> escape back",
        "",
        "On success: repeat the cycle",
        "On fail:    retry escape (up to 2x)",
        "            then flee and stop",
        "Target dead or gone: stop",
        "After 10s with no activity: stop",
    }
})
as_dbg("loaded — alias as<dir> registered")
