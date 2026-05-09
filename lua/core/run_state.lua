-- Run XP/TP tracker and kill announcer.
-- Subscribes to gmcp_char_vitals for baseline + running totals only.
-- Subscribes to mob_death; queues mob names and schedules a debounced fold
-- (run_fold, 500ms) so multiple R.I.P. lines from one combat round
-- batch into a single fold. Killing-blow XP is already in state.char.xp by
-- the time mob_death fires (MUME emits Vitals before R.I.P.).
-- Exposes state.run (read side) and state.run.reset() for lifecycle hooks.

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
    xp_baseline    = nil,    -- xp at run start; nil = not yet known
    tp_baseline    = nil,
    xp             = 0,
    tp             = 0,
    last_fold_xp   = nil,    -- xp snapshot at last fold (or run start)
    last_tp        = nil,    -- tp at last Vitals tick (or run start)
    pending_kills  = {},     -- mob names awaiting attribution
    kills          = {},     -- append-only per run: { name, xp }
    deaths         = 0,
    pkills         = {},     -- append-only per run: { name, race, xp }
    pending_pkills = {},     -- pc names awaiting attribution
}

function M.reset()
    M.xp_baseline    = nil
    M.tp_baseline    = nil
    M.last_fold_xp   = nil
    M.last_tp        = nil
    M.xp             = 0
    M.tp             = 0
    M.pending_kills  = {}
    M.kills          = {}
    M.deaths         = 0
    M.pkills         = {}
    M.pending_pkills = {}
    session_cmd("#undelay {run_fold}")
end

state.run = M

events.subscribe("gmcp_char_vitals", function(body)
    if not body then return end

    if body.xp then
        if M.xp_baseline == nil then
            M.xp_baseline  = body.xp
            M.last_fold_xp = body.xp
            M.xp           = 0
        elseif body.xp < M.last_fold_xp then
            -- death penalty / level loss → rebaseline, drop pending
            M.xp_baseline    = body.xp
            M.last_fold_xp   = body.xp
            M.xp             = 0
            M.pending_kills  = {}
            M.pending_pkills = {}
        else
            M.xp = body.xp - M.xp_baseline
        end
    end
    if body.tp then
        if M.tp_baseline == nil then
            M.tp_baseline = body.tp
            M.last_tp     = body.tp
            M.tp          = 0
        elseif body.tp < M.last_tp then
            -- tp drop (death penalty / trainer-spend) → silent rebaseline
            M.tp_baseline = body.tp
            M.last_tp     = body.tp
            M.tp          = 0
        elseif body.tp > M.last_tp then
            events.emit("tp_gained", { delta = body.tp - M.last_tp })
            M.last_tp = body.tp
            M.tp      = body.tp - M.tp_baseline
        end
        -- body.tp == M.last_tp is a no-op; M.tp is already correct
    end
end)

local function schedule_fold()
    session_cmd(string.format(
        "#delay {run_fold} {#lua {state.run._fold()}} {%s}",
        FOLD_DELAY))
end

events.subscribe("mob_death", function(name)
    table.insert(M.pending_kills, name)
    schedule_fold()
end)

events.subscribe("char_death", function()
    M.deaths = M.deaths + 1
end)

events.subscribe("pc_death", function(full)
    local name = full:match("^(%S+)")
    local race = full:match("^%S+%s+(.*)$") or ""
    table.insert(M.pending_pkills, { name = name, race = race })
    schedule_fold()
end)

function M._fold()
    local nk = #M.pending_kills
    local np = #M.pending_pkills
    local n  = nk + np
    dbg("[RUN_STATE] fold fired, kills=" .. nk .. " pkills=" .. np)

    if n == 0 then return end

    local current_xp = state.char.xp or M.last_fold_xp
    local pending_xp = current_xp - M.last_fold_xp
    if pending_xp < 0 then pending_xp = 0 end

    local per = math.floor(pending_xp / n)
    local rem = pending_xp - per * n

    local idx = 0

    for _, name in ipairs(M.pending_kills) do
        idx = idx + 1
        local xp = per
        if idx == n then xp = xp + rem end
        table.insert(M.kills, { name = name, xp = xp })
        script_ui("KILL", ui_var(name) .. ", " .. ui_var(fmt_xp(xp)) .. " xp.")
        events.emit("kill_attributed", { name = name, xp = xp })
    end

    for _, pk in ipairs(M.pending_pkills) do
        idx = idx + 1
        local xp = per
        if idx == n then xp = xp + rem end
        table.insert(M.pkills, { name = pk.name, race = pk.race, xp = xp })
        script_ui("PKILL", ui_var(pk.name) .. ", " .. ui_var(fmt_xp(xp)) .. " xp.")
        events.emit("pkill_attributed", { name = pk.name, race = pk.race, xp = xp })
    end

    M.last_fold_xp   = current_xp
    M.pending_kills  = {}
    M.pending_pkills = {}
end

dbg("[RUN_STATE] loaded")
