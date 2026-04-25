-- Session XP/TP tracker and kill announcer.
-- Wraps Char.Vitals for baseline + running totals only.
-- Subscribes to mob_death; queues mob names and schedules a debounced fold
-- (sess_kills_fold, 100ms) so multiple R.I.P. lines from one combat round
-- batch into a single fold. Killing-blow XP is already in state.char.xp by
-- the time mob_death fires (MUME emits Vitals before R.I.P.).
-- Exposes state.session (read side) and state.session.reset() for lifecycle hooks.

local FOLD_DELAY = 0.5  -- seconds; brief window to batch group kills

local function fmt_xp(n)
    n = math.floor(n)
    if n < 1000 then
        return tostring(n)
    elseif n < 10000 then
        return string.format("%.1fk", n / 1000)
    else
        return string.format("%dk", math.floor(n / 1000))
    end
end

local M = {
    xp_baseline   = nil,    -- xp at session start; nil = not yet known
    tp_baseline   = nil,
    session_xp    = 0,
    session_tp    = 0,
    last_fold_xp  = nil,    -- xp snapshot at last fold (or session start)
    pending_kills = {},     -- mob names awaiting attribution
    kills         = {},     -- append-only per session: { name, xp }
}

function M.reset()
    M.xp_baseline   = nil
    M.tp_baseline   = nil
    M.last_fold_xp  = nil
    M.session_xp    = 0
    M.session_tp    = 0
    M.pending_kills = {}
    M.kills         = {}
    session_cmd("#undelay {sess_kills_fold}")
end

state.session = M

local _orig_vitals = gmcp.handlers["Char.Vitals"]

gmcp.handlers["Char.Vitals"] = function(body)
    if _orig_vitals then _orig_vitals(body) end
    if not body then return end

    if body.xp then
        if M.xp_baseline == nil then
            M.xp_baseline  = body.xp
            M.last_fold_xp = body.xp
            M.session_xp   = 0
        elseif body.xp < M.last_fold_xp then
            -- death penalty / level loss → rebaseline, drop pending
            M.xp_baseline   = body.xp
            M.last_fold_xp  = body.xp
            M.session_xp    = 0
            M.pending_kills = {}
        else
        M.session_xp = body.xp - M.xp_baseline
        end
    end
    if body.tp then
        if M.tp_baseline == nil then
            M.tp_baseline  = body.tp
            M.last_fold_tp = body.tp
            M.session_tp   = 0
        elseif body.tp < M.last_fold_tp then
            -- death penalty / level loss → rebaseline, drop pending
            M.tp_baseline   = body.tp
            M.last_fold_tp  = body.tp
            M.session_tp    = 0
        else
            M.session_tp = body.tp - M.tp_baseline
        end
    end

    return
end

local function schedule_fold()
    session_cmd(string.format(
        "#delay {sess_kills_fold} {#lua {state.session._fold()}} {%s}",
        FOLD_DELAY))
end

events.subscribe("mob_death", function(name)
    table.insert(M.pending_kills, name)
    schedule_fold()
end)

function M._fold()
    dbg("[SESS_KILLS] fold fired, pending=" .. #M.pending_kills)

    local n = #M.pending_kills
    if n == 0 then return end

    local current_xp = state.char.xp or M.last_fold_xp
    local pending_xp = current_xp - M.last_fold_xp
    if pending_xp < 0 then pending_xp = 0 end

    local per = math.floor(pending_xp / n)
    local rem = pending_xp - per * n

    for i, name in ipairs(M.pending_kills) do
        local xp = per
        if i == n then xp = xp + rem end
        table.insert(M.kills, { name = name, xp = xp })
        script_ui("KILL", ui_var(name) .. ", " .. ui_var(fmt_xp(xp)) .. " xp.")
    end

    M.last_fold_xp  = current_xp
    M.pending_kills = {}
end

dbg("[SESS_KILLS] loaded")
