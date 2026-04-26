-- Wraps Comm.Channel.Text and Comm.Channel.List handlers from comm_log.lua.
-- Owns state.comm.filters and state.comm.toggle().
-- Reads bridge/comm_filters.conf on load; writes it on every toggle.
-- Serialises the projection to bridge/comm.state on every change.
--
-- Disconnect policy: state.comm.history is NOT cleared on SESSION DISCONNECTED.
-- Channel history is retained across reconnects within the same brain process.
-- cp -r clears it via Lua restart. See docs/comm-pane.md for rationale.

local json = require("dkjson")
local COMM_STATE_PATH   = os.getenv("HOME") .. "/MUME/bridge/comm.state"
local COMM_FILTERS_CONF = os.getenv("HOME") .. "/MUME/bridge/comm_filters.conf"
local TMP_PATH          = COMM_STATE_PATH .. ".tmp"

-- Read bridge/comm_filters.conf into state.comm.filters.
-- Format: one "name=true|false" line per explicitly-set channel.
-- Missing file is fine — all channels default to enabled.
local function _load_filters()
    local f = io.open(COMM_FILTERS_CONF, "r")
    if not f then return end
    for line in f:lines() do
        local name, val = line:match("^([^=]+)=(true|false)$")
        if name and val then
            state.comm.filters[name] = (val == "true")
        end
    end
    f:close()
end

-- Write state.comm.filters to bridge/comm_filters.conf.
-- Only stores entries that were explicitly set (sparse map).
local function _save_filters()
    local f = io.open(COMM_FILTERS_CONF, "w")
    if not f then
        dbg("[COMM_STATE] cannot write comm_filters.conf")
        return
    end
    for name, val in pairs(state.comm.filters) do
        f:write(name .. "=" .. tostring(val) .. "\n")
    end
    f:close()
end

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
        filters  = state.comm.filters,
        history  = state.comm.history,
    }
    local encoded = json.encode(payload)
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[COMM_STATE] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, COMM_STATE_PATH)
end

-- state.comm.toggle(name) — flip filter for a named channel, persist, serialize.
-- No-op with a dbg() warning if name is unknown.
state.comm.toggle = function(name)
    local found = false
    for _, ch in ipairs(state.comm.channels or {}) do
        if ch.name == name then found = true; break end
    end
    if not found then
        dbg("[COMM_STATE] toggle: unknown channel: " .. tostring(name))
        return
    end
    -- Sparse map: nil means enabled (true). Flip the effective value.
    local current = state.comm.filters[name]
    if current == nil then current = true end
    state.comm.filters[name] = not current
    _save_filters()
    serialize()
end

-- Wrap existing handlers: call original first, then serialize.
-- comm_log.lua loads before comm_state.lua (alphabetical order).
local _orig_text = gmcp.handlers["Comm.Channel.Text"]
local _orig_list = gmcp.handlers["Comm.Channel.List"]

gmcp.handlers["Comm.Channel.Text"] = function(body)
    if _orig_text then _orig_text(body) end
    serialize()
end

gmcp.handlers["Comm.Channel.List"] = function(body)
    if _orig_list then _orig_list(body) end
    serialize()
end

_load_filters()
serialize()
dbg("[COMM_STATE] loaded")
