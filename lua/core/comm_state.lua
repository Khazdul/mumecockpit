-- Wraps Comm.Channel.Text and Comm.Channel.List handlers from comm_log.lua.
-- Serialises history and channels to bridge/comm.state on every change.
-- Reads bridge/comm.state at load time to restore history and channels after
-- cp -r, working around one-shot Comm.Channel.List on persistent connections.
-- Filter state is owned by bridge/comm_pane.py; this file does not touch it.
--
-- Disconnect policy: state.comm.history is NOT cleared on SESSION DISCONNECTED.
-- Channel history is retained across reconnects within the same brain process.
-- cp -r restarts Lua; _load_state_file() repopulates from the previous run.

local json = require("dkjson")
local COMM_STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/comm.state"
local TMP_PATH        = COMM_STATE_PATH .. ".tmp"

-- Build channels list with computed label.
-- Label = first letter of name, uppercased. Collision policy: fall back to
-- 2nd char, 3rd char, etc. Deterministic by Comm.Channel.List order.
-- Document in docs/comm-pane.md.
local function _build_channels()
    local used   = {}
    local result = {}
    for _, ch in ipairs(state.comm.channels or {}) do
        local name = ch.name or ""
        local label = nil
        for i = 1, #name do
            local c = name:sub(i, i):upper()
            if c:match("[A-Z]") and not used[c] then
                label = c
                used[c] = true
                break
            end
        end
        if not label then label = "?" end
        result[#result + 1] = {
            name    = name,
            label   = label,
            caption = ch.caption or name,
        }
    end
    return result
end

local function serialize()
    local payload = {
        channels = _build_channels(),
        history  = state.comm.history,
    }
    local encoded, enc_err = json.encode(payload)
    if type(encoded) ~= "string" then
        dbg("[COMM_STATE] json encode failed: " .. tostring(enc_err))
        return
    end
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[COMM_STATE] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, COMM_STATE_PATH)
end

-- Read bridge/comm.state at load to restore history and channels from the
-- previous run. Non-fatal: any error leaves state empty and continues.
local function _load_state_file()
    local f = io.open(COMM_STATE_PATH, "r")
    if not f then return end
    local raw = f:read("*a")
    f:close()
    local ok, decoded = pcall(json.decode, raw)
    if not ok or type(decoded) ~= "table" then
        dbg("[COMM_STATE] load_state_file: decode failed")
        return
    end
    -- Restore history (clamped to max_size)
    if type(decoded.history) == "table" then
        local h = decoded.history
        local max = state.comm.max_size or 500
        if #h > max then
            local trimmed = {}
            for i = #h - max + 1, #h do trimmed[#trimmed + 1] = h[i] end
            h = trimmed
        end
        state.comm.history = h
    end
    -- Restore channels (name + caption only; label is re-derived in serialize)
    if type(decoded.channels) == "table" then
        local ch = {}
        for _, entry in ipairs(decoded.channels) do
            if type(entry) == "table" and entry.name then
                ch[#ch + 1] = { name = entry.name, caption = entry.caption or entry.name }
            end
        end
        state.comm.channels = ch
    end
end

-- Wrap existing handlers: call original first, then serialize.
-- comm_log.lua loads before comm_state.lua (alphabetical order).
local _orig_text = gmcp.handlers["Comm.Channel.Text"]
local _orig_list = gmcp.handlers["Comm.Channel.List"]

---@diagnostic disable-next-line: duplicate-set-field
gmcp.handlers["Comm.Channel.Text"] = function(body)
    if _orig_text then _orig_text(body) end
    serialize()
end

---@diagnostic disable-next-line: duplicate-set-field
gmcp.handlers["Comm.Channel.List"] = function(body)
    if _orig_list then _orig_list(body) end
    serialize()
end

_load_state_file()
serialize()
dbg("[COMM_STATE] loaded")
