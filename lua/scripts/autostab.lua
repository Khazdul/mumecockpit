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
-- are registered dynamically by M.start() and cleaned up on abort.
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

local M = {}
scripts.autostab = M

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
    session_cmd("#action {You successfully escaped the fight!} {#lua {scripts.autostab.on_success()}}")
    session_cmd("#action {You failed to escape the fight!} {#lua {scripts.autostab.on_fail()}}")
end

local function unregister_triggers()
    session_cmd("#unaction {You successfully escaped the fight!}")
    session_cmd("#unaction {You failed to escape the fight!}")
end

-- -----------------------------
-- WATCHDOG
-- Calling reset_watchdog() again replaces the existing delay (natural reset).
-- -----------------------------

local function reset_watchdog()
    session_cmd(string.format("#delay {as_watch} {#lua {scripts.autostab.watchdog()}} {%d}", WATCH_TIMEOUT))
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
    events.unsubscribe("mob_death", M.on_mob_death)
    session_cmd("#undelay {as_watch}")
    as_dbg("stopped: " .. reason)
    script_ui("AUTOSTAB", "Stopped — " .. ui_var(reason) .. ".")
end

-- -----------------------------
-- PUBLIC API (called via #lua from tt++ triggers/aliases/delays)
-- -----------------------------

function M.start(dir, target)
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
        events.unsubscribe("mob_death", M.on_mob_death)
        session_cmd("#undelay {as_watch}")
    end

    as.active      = true
    as.dir         = dir
    as.ret         = RET[dir]
    as.target      = target
    as.retry_count = 0

    register_triggers()
    events.subscribe("mob_death", M.on_mob_death)
    reset_watchdog()

    as_dbg(string.format("start %s←%s target=%s", dir, as.ret, target))
    as_show(string.format("target: %s dir: %s", as.target, as.dir))
    script_ui("AUTOSTAB", "Running.")
    do_cycle()
end

function M.on_success()
    if not as.active then return end
    as.retry_count = 0
    reset_watchdog()
    do_cycle()
end

function M.on_fail()
    if not as.active then return end
    as.retry_count = as.retry_count + 1
    reset_watchdog()
    if as.retry_count <= 2 then
        as_dbg(string.format("escape fail %d/2 — retry", as.retry_count))
        send("escape " .. as.ret)
    else
        as_dbg("3 fails — flee+abort")
        send("flee")
        abort("fled")
    end
end

function M.on_mob_death(_)
    if not as.active then return end
    abort("target dead")
end

function M.watchdog()
    if not as.active then return end
    -- Watchdog already fired — no need to #undelay, just clean up triggers
    as.active = false
    unregister_triggers()
    as_dbg(string.format("watchdog: no activity for %ds — stopped", WATCH_TIMEOUT))
    script_ui("AUTOSTAB", "Stopped — timed out.")
end

-- -----------------------------
-- SETUP — register alias on load, declare metadata
-- -----------------------------
game_cmd('#alias {as%1} {#lua {scripts.autostab.start("%1", "$target")}}')
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
as_dbg("loaded")
