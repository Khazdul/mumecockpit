-- Per-character JSONL archive for state.comm.history.
-- Loads after comm_state.lua (alphabetical: comm_log < comm_state < comm_store).
-- On Char.Name: migrates legacy profile archive if character name matches profile,
-- prunes entries older than 7 days, seeds state.comm.history from the archive,
-- and calls state.comm.serialize() so bridge/comm.state reflects the seeded
-- history before the pane's next 250 ms poll.
-- On each Comm.Channel.Text event: appends one JSON line to the archive.

local json = require("dkjson")

local DATA_COMM_DIR   = os.getenv("HOME") .. "/MUME/data/comm/"
local OLD_ARCHIVE_DIR = os.getenv("HOME") .. "/MUME/logs/comm_archive/"
local STARTUP_CONF    = os.getenv("HOME") .. "/MUME/bridge/startup.conf"
local RETAIN_SECONDS  = 7 * 86400

local function _read_conf_value(path, key)
    local f = io.open(path, "r")
    if not f then return nil end
    for line in f:lines() do
        local k, v = line:match("^([^=]+)=(.*)$")
        if k == key then f:close(); return v end
    end
    f:close()
    return nil
end

-- Read profile once at load time — used only for the one-time migration.
local _profile = _read_conf_value(STARTUP_CONF, "profile") or "default"

local _archive_path = nil  -- set on Char.Name
local _tmp_path     = nil  -- set on Char.Name

local function _init(char_name)
    _archive_path = DATA_COMM_DIR .. char_name .. ".jsonl"
    _tmp_path     = _archive_path .. ".tmp"

    -- One-time migration: move legacy profile archive when profile matches character.
    do
        local fn = io.open(_archive_path, "r")
        if not fn and _profile == char_name then
            local old = OLD_ARCHIVE_DIR .. _profile .. ".jsonl"
            local fo = io.open(old, "r")
            if fo then
                fo:close()
                if os.rename(old, _archive_path) then
                    dbg("[COMM_STORE] migrated comm_archive/" .. _profile .. ".jsonl")
                    os.execute("rmdir '" .. OLD_ARCHIVE_DIR .. "' 2>/dev/null")
                end
            end
        elseif fn then
            fn:close()
        end
    end

    -- Read archive and filter to the 7-day window.
    local entries = {}
    local cutoff  = os.time() - RETAIN_SECONDS
    local rf = io.open(_archive_path, "r")
    if rf then
        for line in rf:lines() do
            if line ~= "" then
                local ok, entry = pcall(json.decode, line)
                if ok and type(entry) == "table" and type(entry.ts) == "number" then
                    if entry.ts >= cutoff then
                        entries[#entries + 1] = entry
                    end
                end
            end
        end
        rf:close()
    end

    -- Prune: atomically rewrite with the filtered set.
    local wf = io.open(_tmp_path, "w")
    if wf then
        for _, e in ipairs(entries) do
            wf:write(json.encode(e) .. "\n")
        end
        wf:close()
        os.rename(_tmp_path, _archive_path)
    end

    -- Clamp to max_size, keeping the most recent entries.
    local max = state.comm.max_size
    if #entries > max then
        local trimmed = {}
        for i = #entries - max + 1, #entries do
            trimmed[#trimmed + 1] = entries[i]
        end
        entries = trimmed
    end
    state.comm.history = entries

    -- Write bridge/comm.state so the pane picks up seeded history on next poll.
    state.comm.serialize()
    dbg("[COMM_STORE] init: " .. char_name .. " (" .. #entries .. " entries)")
end

-- Wrap Comm.Channel.Text to append each new message to the archive.
-- comm_state.lua's wrapper (which calls comm_log.lua then serialize) is _orig.
local _orig = gmcp.handlers["Comm.Channel.Text"]

---@diagnostic disable-next-line: duplicate-set-field
gmcp.handlers["Comm.Channel.Text"] = function(body)
    if _orig then _orig(body) end
    if not _archive_path then return end  -- Char.Name not yet received
    local entry = state.comm.history[#state.comm.history]
    if not entry then
        dbg("[COMM_STORE] Comm.Channel.Text: no entry in history after handler")
        return
    end
    local af = io.open(_archive_path, "a")
    if af then
        af:write(json.encode(entry) .. "\n")
        af:close()
    end
end

-- Wrap Char.Name to initialize the per-character archive on login.
local _orig_name = gmcp.handlers["Char.Name"]

---@diagnostic disable-next-line: duplicate-set-field
gmcp.handlers["Char.Name"] = function(body)
    if _orig_name then _orig_name(body) end
    local name = state.char.name
    if name then
        _archive_path = nil
        _tmp_path     = nil
        _init(name)
    end
end

dbg("[COMM_STORE] loaded")
