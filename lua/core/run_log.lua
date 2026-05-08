-- Per-character JSONL run log. Writes run_start (deferred to first Vitals),
-- level_up, and run_end rows to data/runs/<character>/current.jsonl.
-- Sealed to <run-id>.jsonl on run_ending. Open-append-close per row.
-- Orphan-handling and cp -r mid-run recovery deferred to Phase 4.

local json = require("dkjson")

local SCHEMA_VERSION = 1

local _active           = false
local _pending_baseline = false
local _run_start_ts     = nil
local _last_level       = nil
local _archive_dir      = nil
local _current_path     = nil

local function _clear_state()
    _active           = false
    _pending_baseline = false
    _run_start_ts     = nil
    _last_level       = nil
    _archive_dir      = nil
    _current_path     = nil
end

local function _append(row)
    local encoded, err = json.encode(row)
    if not encoded then
        dbg("[RUN_LOG] json encode failed: " .. tostring(err))
        return
    end
    local f = io.open(_current_path, "a")
    if not f then
        dbg("[RUN_LOG] open failed: " .. tostring(_current_path))
        return
    end
    f:write(encoded .. "\n")
    f:close()
end

events.subscribe("run_started", function()
    local name = state.char and state.char.name
    if not name then
        dbg("[RUN_LOG] run_started: no char name, skipping")
        return
    end
    _archive_dir  = os.getenv("HOME") .. "/MUME/data/runs/" .. name .. "/"
    _current_path = _archive_dir .. "current.jsonl"
    os.execute("mkdir -p '" .. _archive_dir .. "' 2>/dev/null")
    _active           = true
    _pending_baseline = true
    _last_level       = nil
    dbg("[RUN_LOG] run_started: " .. name)
end)

events.subscribe("gmcp_char_vitals", function()
    if not _active then return end
    if not _pending_baseline then return end
    local ts = os.time()
    _run_start_ts = ts
    _append({
        event     = "run_start",
        ts        = ts,
        character = state.char and state.char.name,
        level     = state.char and state.char.level,
        xp        = state.char and state.char.xp,
        tp        = state.char and state.char.tp,
        schema    = SCHEMA_VERSION,
    })
    _pending_baseline = false
    dbg("[RUN_LOG] run_start written")
end)

events.subscribe("gmcp_char_status_vars", function()
    if not _active then return end
    local level = state.char and state.char.level
    if not level then return end
    if _last_level == nil then
        _last_level = level
        return
    end
    if level > _last_level then
        _append({ event = "level_up", ts = os.time(), level = level })
        dbg("[RUN_LOG] level_up: " .. tostring(level))
        _last_level = level
    end
end)

events.subscribe("kill_attributed", function(payload)
    if not _active then return end
    _append({
        event    = "kill",
        ts       = os.time(),
        mob_name = payload.name,
        xp_delta = payload.xp,
    })
    dbg("[RUN_LOG] kill: " .. tostring(payload.name) .. " xp=" .. tostring(payload.xp))
end)

events.subscribe("run_ending", function()
    if not _active then return end
    if _pending_baseline then
        -- Disconnected before first Vitals arrived; no file was written.
        _clear_state()
        dbg("[RUN_LOG] run_ending: no baseline, nothing to seal")
        return
    end
    _append({ event = "run_end", ts = os.time() })
    local run_id = os.date("%Y-%m-%dT%H-%M-%S", _run_start_ts)
    local sealed = _archive_dir .. run_id .. ".jsonl"
    local ok     = os.rename(_current_path, sealed)
    if not ok then
        ui_warn("RUN_LOG: failed to seal current.jsonl → " .. run_id .. ".jsonl; orphan may remain.")
    else
        dbg("[RUN_LOG] sealed: " .. run_id .. ".jsonl")
    end
    _clear_state()
end)

dbg("[RUN_LOG] loaded")
