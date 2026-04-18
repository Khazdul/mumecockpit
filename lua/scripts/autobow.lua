-- ===== AUTOBOW =====
-- Self-contained script. Registers alias on load — no paired .tin file needed.
--
-- Alias:  ash<dir>  (e.g. ashe = autobow east)
--
-- Crossbow path:
--   draw -> load -> (wait for on_loaded) -> go dir -> shoot $target -> escape retDir
--   on escape success: draw -> reload -> repeat cycle
--
-- Bow path:
--   draw -> go dir -> shoot $target -> escape retDir
--   on escape success: draw -> shoot immediately (no load), repeat cycle
--
-- Weapon auto-detection:
--   ab.weapon starts nil each session. "load" is always sent first when weapon
--   is unknown. The server response determines the type:
--     "You load %1 into your crossbow." -> weapon="crossbow", proceed to shoot
--     "But your crossbow is already loaded!" -> weapon="crossbow", proceed to shoot
--     "You can only load crossbows."  -> weapon="bow", skip reload, proceed to shoot
--   Once detected, ab.weapon persists across runs within the same session.
--   A fresh autobow_start() preserves the detected value — no re-detection needed.
--
-- MUD triggers (loaded/already_loaded/not_crossbow/success/fail/dead/gone)
-- and watchdog (ab_watch) are registered dynamically by autobow_start()
-- and cleaned up on abort.
-- Watchdog fires if no trigger is seen within WATCH_TIMEOUT seconds.

local RET           = { n="s", s="n", e="w", w="e", u="d", d="u" }
local WATCH_TIMEOUT = 15  -- seconds with no activity before auto-cancel

local ab = {
    active      = false,
    dir         = nil,
    ret         = nil,
    target      = nil,
    retry_count = 0,
    weapon      = nil,   -- nil=unknown, "crossbow", "bow"
}

local function ab_dbg(msg)
    dbg("[AUTOBOW] " .. msg)
end

local function ab_show(msg)
    tintin_show(GAME_SESSION or "gts", "<F9AA8B7>## AUTOBOW: <FFFFFFF>" .. msg .. "<099>")
end

-- -----------------------------
-- TRIGGER LIFECYCLE
-- -----------------------------

local function register_triggers()
    session_cmd("#action {You load %1 into your crossbow.} {#lua {autobow_on_loaded()}}")
    session_cmd("#action {But your crossbow is already loaded!} {#lua {autobow_on_already_loaded()}}")
    session_cmd("#action {You can only load crossbows.} {#lua {autobow_on_not_crossbow()}}")
    session_cmd("#action {You successfully escaped the fight!} {#lua {autobow_on_success()}}")
    session_cmd("#action {You failed to escape the fight!} {#lua {autobow_on_fail()}}")
    session_cmd("#action {%1 is dead! R.I.P.} {#lua {autobow_on_dead()}}")
    session_cmd("#action {%1 disappears into nothing.} {#lua {autobow_on_gone()}}")
    session_cmd("#action {You don't have any bolts.} {#lua {autobow_on_no_bolts()}}")
    session_cmd("#action {You don't have any arrows.} {#lua {autobow_on_no_arrows()}}")
end

local function unregister_triggers()
    session_cmd("#unaction {You load %1 into your crossbow.}")
    session_cmd("#unaction {But your crossbow is already loaded!}")
    session_cmd("#unaction {You can only load crossbows.}")
    session_cmd("#unaction {You successfully escaped the fight!}")
    session_cmd("#unaction {You failed to escape the fight!}")
    session_cmd("#unaction {%1 is dead! R.I.P.}")
    session_cmd("#unaction {%1 disappears into nothing.}")
    session_cmd("#unaction {You don't have any bolts.}")
    session_cmd("#unaction {You don't have any arrows.}")
end

-- -----------------------------
-- WATCHDOG
-- Calling reset_watchdog() again replaces the existing delay (natural reset).
-- -----------------------------

local function reset_watchdog()
    session_cmd(string.format("#delay {ab_watch} {#lua {autobow_watchdog()}} {%d}", WATCH_TIMEOUT))
end

-- -----------------------------
-- INTERNAL
-- -----------------------------

local function do_shoot()
    send(ab.dir)
    send("shoot " .. ab.target)
    send("escape " .. ab.ret)
end

local function do_load_or_shoot()
    if ab.weapon == "bow" then
        do_shoot()
    else
        if ab.weapon == "crossbow" then
            tintin_show("mume", "<F719FC7>reloading...<099>")
        end
        send("load")
    end
end

local function abort(reason)
    ab.active = false
    unregister_triggers()
    session_cmd("#undelay {ab_watch}")
    ab_dbg("stopped: " .. reason)
    script_ui("AUTOBOW", "Stopped — " .. reason)
end

-- -----------------------------
-- PUBLIC API (called via #lua from tt++ triggers/aliases/delays)
-- -----------------------------

function autobow_start(dir, target)
    if not RET[dir] then
        ab_show("bad direction: " .. tostring(dir))
        return
    end
    if not target or target == "" then
        ab_show("no target set — use 'z <name>' first")
        return
    end

    -- Clean up any still-running session before starting fresh
    if ab.active then
        unregister_triggers()
        session_cmd("#undelay {ab_watch}")
    end

    ab.active      = true
    ab.dir         = dir
    ab.ret         = RET[dir]
    ab.target      = target
    ab.retry_count = 0
    -- NOTE: ab.weapon is intentionally preserved — no reset here

    register_triggers()
    reset_watchdog()

    ab_dbg(string.format("start %s←%s target=%s [%s]", dir, ab.ret, target, tostring(ab.weapon)))
    ab_show(string.format("target: %s dir: %s", ab.target, ab.dir))
    script_ui("AUTOBOW", "Running")
    send("draw bow")
    do_load_or_shoot()
end

function autobow_on_loaded()
    if not ab.active then return end
    ab.weapon = "crossbow"
    reset_watchdog()
    do_shoot()
end

function autobow_on_already_loaded()
    if not ab.active then return end
    ab.weapon = "crossbow"
    reset_watchdog()
    do_shoot()
end

function autobow_on_not_crossbow()
    if not ab.active then return end
    ab.weapon = "bow"
    reset_watchdog()
    ab_dbg("bow detected")
    do_shoot()
end

function autobow_on_success()
    if not ab.active then return end
    ab.retry_count = 0
    reset_watchdog()
    do_load_or_shoot()
end

function autobow_on_fail()
    if not ab.active then return end
    ab.retry_count = ab.retry_count + 1
    reset_watchdog()
    if ab.retry_count <= 2 then
        ab_dbg(string.format("escape fail %d/2 — retry", ab.retry_count))
        send("escape " .. ab.ret)
    else
        ab_dbg("3 fails — flee+abort")
        send("flee")
        abort("fled")
    end
end

function autobow_on_dead()
    if not ab.active then return end
    abort("dead")
end

function autobow_on_gone()
    if not ab.active then return end
    abort("gone")
end

function autobow_on_no_bolts()
    if not ab.active then return end
    abort("out of bolts")
end

function autobow_on_no_arrows()
    if not ab.active then return end
    send("escape " .. ab.ret)
    abort("out of arrows")
end

function autobow_watchdog()
    if not ab.active then return end
    -- Watchdog already fired — no need to #undelay, just clean up triggers
    ab.active = false
    unregister_triggers()
    ab_dbg("watchdog timeout")
    script_ui("AUTOBOW", "Stopped — timed out")
end

-- -----------------------------
-- SETUP — register alias on load, declare metadata
-- -----------------------------
game_cmd('#alias {ash%1} {#lua {autobow_start("%1", "$target")}} {4}')
register_script({
    alias   = "autobow",
    summary = "bow/crossbow shoot/escape loop",
    help    = {
        "Usage:  ash<dir>   e.g. ashe = autobow east",
        "        Set target first: z <n>",
        "",
        "Weapon type is auto-detected on first shot.",
        "Crossbow: reloads between shots.",
        "Bow: shoots immediately each cycle.",
        "",
        "Cycle:",
        "  draw -> load? -> go dir -> shoot -> escape back",
        "",
        "On fail:    retry escape (up to 2x)",
        "            then flee and stop",
        "Target dead or gone: stop",
        "After 15s with no activity: stop",
    }
})
ab_dbg("loaded — alias ash<dir> registered")
