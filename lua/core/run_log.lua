-- Per-character JSONL run log. Writes run_start (deferred to first Vitals),
-- level_up, kill, and run_end rows to data/runs/<character>/current.jsonl.
-- Sealed to <run-id>.jsonl on run_ending. Open-append-close per row.

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

-- Read the numeric `ts` field from the first line of path, or return nil.
local function _read_first_ts(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local line = f:read("*l")
    f:close()
    if not line then return nil end
    local decoded = json.decode(line)
    if decoded and type(decoded.ts) == "number" then return decoded.ts end
    return nil
end

-- Append orphan_close and rename current.jsonl to a sealed run-id file.
local function _seal_orphan(path, archive_dir, name)
    local original_ts = _read_first_ts(path)
    if not original_ts then
        dbg("[RUN_LOG] orphan first-line unreadable, using now as ts")
        original_ts = os.time()
    end
    local af = io.open(path, "a")
    if af then
        local row = json.encode({ event = "orphan_close", ts = os.time() })
        if row then af:write(row .. "\n") end
        af:close()
    end
    local sealed = archive_dir .. os.date("%Y-%m-%dT%H-%M-%S", original_ts) .. ".jsonl"
    local ok = os.rename(path, sealed)
    if not ok then
        ui_warn("RUN_LOG: failed to seal orphan current.jsonl; will retry next login.")
        return
    end
    dbg("[RUN_LOG] sealed orphan for " .. tostring(name))
end

events.subscribe("run_started", function()
    local name = state.char and state.char.name
    if not name then
        dbg("[RUN_LOG] run_started: no char name, skipping")
        return
    end
    local archive_dir  = os.getenv("HOME") .. "/MUME/data/runs/" .. name .. "/"
    local current_path = archive_dir .. "current.jsonl"
    os.execute("mkdir -p '" .. archive_dir .. "' 2>/dev/null")
    -- Orphan-detection: seal any leftover current.jsonl from a prior unsealed run.
    local probe = io.open(current_path, "r")
    if probe then
        probe:close()
        _seal_orphan(current_path, archive_dir, name)
    end
    _archive_dir      = archive_dir
    _current_path     = current_path
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

-- cp -r mid-run resume: state.char.name is populated here iff Phase 1 rehydrated it
-- from connection.state (written by the previous brain while MUME was connected).
-- connection.state is cleared unconditionally before load_scripts() runs, so its
-- *presence* cannot be used — state.char.name is the surviving signal.
local _resume_name = state.char and state.char.name
if _resume_name then
    local archive_dir  = os.getenv("HOME") .. "/MUME/data/runs/" .. _resume_name .. "/"
    local current_path = archive_dir .. "current.jsonl"
    local f = io.open(current_path, "r")
    if not f then
        -- Anomaly: mid-run signal but no current.jsonl (crash before first Vitals).
        dbg("[RUN_LOG] resume: state.char.name set but no current.jsonl; starting fresh on next Vitals")
        _archive_dir      = archive_dir
        _current_path     = current_path
        _active           = true
        _pending_baseline = true
        _last_level       = nil
    else
        local first = f:read("*l")
        f:close()
        local run_start_ts
        if first then
            local decoded = json.decode(first)
            if decoded and type(decoded.ts) == "number" then
                run_start_ts = decoded.ts
            end
        end
        if not run_start_ts then
            dbg("[RUN_LOG] resume: first-line parse failed, using now as run_start_ts")
            run_start_ts = os.time()
        end
        _run_start_ts     = run_start_ts
        _archive_dir      = archive_dir
        _current_path     = current_path
        _active           = true
        _pending_baseline = false
        _last_level       = nil
        dbg("[RUN_LOG] resumed run for " .. _resume_name .. " (run_start ts=" .. tostring(run_start_ts) .. ")")
    end
end

dbg("[RUN_LOG] loaded")
