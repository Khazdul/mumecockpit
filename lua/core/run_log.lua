-- Per-character JSONL run log. Writes various run events (run_start, level_up,
-- kill, group_changed, etc.) to data/runs/<character>/current.jsonl.
-- Sealed to <run-id>.jsonl on run_ending. Open-append-close per row.

local json = require("dkjson")

local SCHEMA_VERSION = 1

local _active           = false
local _pending_baseline = false
local _run_start_ts     = nil
local _last_level       = nil
local _archive_dir      = nil
local _current_path     = nil
local _last_allies_key  = ""

local function _clear_state()
    _active           = false
    _pending_baseline = false
    _run_start_ts     = nil
    _last_level       = nil
    _archive_dir      = nil
    _current_path     = nil
    _last_allies_key  = ""
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

-- Arms the tt++ _run_log_path variable so the RECEIVED LINE event handler
-- starts writing timestamped lines to the .log file. Lua only manages the
-- variable; tt++ handles all per-line I/O (no Lua dispatch on the hot path).
-- session_cmd wraps the registration in #class {core} {open}/{close} so
-- _run_log_path lives in {core}, not the profile class — #class write
-- {<profile>} on auto-save correctly excludes it.
local function _open_log(ts)
    if not GAME_SESSION then
        dbg("[RUN_LOG] _open_log: no game session, skipping")
        return
    end
    local log_path = _archive_dir
                     .. os.date("%Y-%m-%dT%H-%M-%S", ts)
                     .. ".log"
    os.execute("touch '" .. log_path .. "' 2>/dev/null")
    session_cmd("#var {_run_log_path} {" .. log_path .. "}")
    dbg("[RUN_LOG] .log path armed: " .. log_path)
end

local function _close_log()
    if not GAME_SESSION then return end
    session_cmd("#unvar _run_log_path")
    dbg("[RUN_LOG] .log path cleared")
end

-- Lexicographic max of `<run-id>.jsonl` files in the archive dir, with the
-- suffix stripped. Run-ids are ISO-like so lexicographic == chronological.
-- Returns nil when no sealed run exists for this character.
local function _find_previous_run_id()
    local p = io.popen("ls -1 '" .. _archive_dir .. "' 2>/dev/null")
    if not p then return nil end
    local latest = nil
    for entry in p:lines() do
        if entry ~= "current.jsonl" then
            local id = entry:match("^(.+)%.jsonl$")
            if id and (latest == nil or id > latest) then
                latest = id
            end
        end
    end
    p:close()
    return latest
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
    if _pending_baseline then
        local ts = os.time()
        _run_start_ts = ts
        local row = {
            event     = "run_start",
            ts        = ts,
            character = state.char and state.char.name,
            level     = state.char and state.char.level,
            xp        = state.char and state.char.xp,
            tp        = state.char and state.char.tp,
            schema    = SCHEMA_VERSION,
        }
        local prev = _find_previous_run_id()
        if prev then row.previous_run_id = prev end
        _append(row)
        _pending_baseline = false
        _open_log(ts)
        dbg("[RUN_LOG] run_start written prev=" .. tostring(prev))
        return
    end
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

events.subscribe("tp_gained", function(payload)
    if not _active then return end
    _append({
        event    = "tp_gained",
        ts       = os.time(),
        tp_delta = payload.delta,
    })
    dbg("[RUN_LOG] tp_gained: " .. tostring(payload.delta))
end)

events.subscribe("xp_loss", function(payload)
    if not _active then return end
    _append({
        event    = "xp_loss",
        ts       = os.time(),
        xp_delta = payload.delta,
    })
    dbg("[RUN_LOG] xp_loss: " .. tostring(payload.delta))
end)

events.subscribe("tp_loss", function(payload)
    if not _active then return end
    _append({
        event    = "tp_loss",
        ts       = os.time(),
        tp_delta = payload.delta,
    })
    dbg("[RUN_LOG] tp_loss: " .. tostring(payload.delta))
end)

events.subscribe("char_death", function()
    if not _active then return end
    local level = nil
    if state.char and state.char.xp then
        level = level_progress.level_from_xp(state.char.xp)
    elseif state.char then
        level = state.char.level
    end
    local row = { event = "char_death", ts = os.time() }
    if level then row.level = level end
    _append(row)
    dbg("[RUN_LOG] char_death: level=" .. tostring(level))
end)

events.subscribe("pkill_attributed", function(payload)
    if not _active then return end
    _append({
        event    = "pkill",
        ts       = os.time(),
        name     = payload.name,
        race     = payload.race,
        xp_delta = payload.xp,
    })
    dbg("[RUN_LOG] pkill: " .. tostring(payload.name) .. " xp=" .. tostring(payload.xp))
end)

events.subscribe("achievement", function(payload)
    if not _active then return end
    _append({ event = "achievement", ts = os.time(), name = payload })
    dbg("[RUN_LOG] achievement: " .. tostring(payload))
end)

local function _on_group_changed()
    if not _active or _pending_baseline then return end
    local ids = {}
    for id in pairs(state.group.members or {}) do ids[#ids + 1] = id end
    table.sort(ids)
    local members = {}
    for _, id in ipairs(ids) do
        local m = state.group.members[id]
        if m and m.type == "ally" and m.name then
            members[#members + 1] = m.name
        end
    end
    local key = table.concat(members, "\0")
    if key == _last_allies_key then return end
    _last_allies_key = key
    _append({ event = "group_changed", ts = os.time(), members = members })
    dbg("[RUN_LOG] group_changed: " .. #members .. " members")
end

events.subscribe("group_member_added",   _on_group_changed)
events.subscribe("group_member_removed", _on_group_changed)

events.subscribe("run_ending", function()
    if not _active then return end
    if _pending_baseline then
        -- Disconnected before first Vitals arrived; no file was written.
        _clear_state()
        dbg("[RUN_LOG] run_ending: no baseline, nothing to seal")
        return
    end
    _append({ event = "run_end", ts = os.time() })
    _close_log()
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
