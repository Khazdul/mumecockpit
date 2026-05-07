-- Serialises history and channels to bridge/runtime/comm.state on every change.
-- Subscribes to gmcp_comm_channel_text and gmcp_comm_channel_list (emitted by
-- dispatch after comm_log.lua's primary writers have updated state.comm.*).
-- Reads bridge/runtime/comm.state at load time to restore channels after cp -r,
-- working around one-shot Comm.Channel.List on persistent connections.
-- History seeding after cp -r is handled by comm_store.lua (loads after this
-- file alphabetically); this file owns channels-only restore.
-- Filter state is owned by bridge/panes/comm_pane.py; this file does not touch it.
--
-- Disconnect policy: state.comm.history is NOT cleared on SESSION DISCONNECTED.
-- Channel history is retained across reconnects within the same brain process.

local json = require("dkjson")
local COMM_STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/runtime/comm.state"
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

-- Read bridge/runtime/comm.state at load to restore channels from the previous run.
-- Non-fatal: any error leaves state empty and continues.
-- History seeding is intentionally omitted here; comm_store.lua owns that.
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

events.subscribe("gmcp_comm_channel_text", function() serialize() end)
events.subscribe("gmcp_comm_channel_list", function() serialize() end)

-- Expose so comm_store.lua can trigger a re-serialise after seeding history.
state.comm.serialize = serialize

_load_state_file()
serialize()
dbg("[COMM_STATE] loaded")
