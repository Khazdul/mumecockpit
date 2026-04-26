-- Per-profile JSONL archive for state.comm.history.
-- Loads after comm_state.lua (alphabetical: comm_log < comm_state < comm_store).
-- On load: prunes entries older than 7 days, seeds state.comm.history from the
-- archive, and calls state.comm.serialize() so bridge/comm.state reflects the
-- seeded history before the pane's next 250 ms poll.
-- On each Comm.Channel.Text event: appends one JSON line to the archive.

local json = require("dkjson")

local ARCHIVE_DIR    = os.getenv("HOME") .. "/MUME/logs/comm_archive/"
local STARTUP_CONF   = os.getenv("HOME") .. "/MUME/bridge/startup.conf"
local RETAIN_SECONDS = 7 * 86400

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

local profile      = _read_conf_value(STARTUP_CONF, "profile") or "default"
local archive_path = ARCHIVE_DIR .. profile .. ".jsonl"
local tmp_path     = archive_path .. ".tmp"

os.execute("mkdir -p '" .. ARCHIVE_DIR .. "'")

-- Read archive and filter to the 7-day window.
local entries = {}
local cutoff  = os.time() - RETAIN_SECONDS
local rf = io.open(archive_path, "r")
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
local wf = io.open(tmp_path, "w")
if wf then
    for _, e in ipairs(entries) do
        wf:write(json.encode(e) .. "\n")
    end
    wf:close()
    os.rename(tmp_path, archive_path)
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

-- Wrap Comm.Channel.Text to append each new message to the archive.
-- comm_state.lua's wrapper (which calls comm_log.lua then serialize) is _orig.
local _orig = gmcp.handlers["Comm.Channel.Text"]

---@diagnostic disable-next-line: duplicate-set-field
gmcp.handlers["Comm.Channel.Text"] = function(body)
    if _orig then _orig(body) end
    local entry = state.comm.history[#state.comm.history]
    if not entry then
        dbg("[COMM_STORE] Comm.Channel.Text: no entry in history after handler")
        return
    end
    local af = io.open(archive_path, "a")
    if af then
        af:write(json.encode(entry) .. "\n")
        af:close()
    end
end

dbg("[COMM_STORE] loaded")
