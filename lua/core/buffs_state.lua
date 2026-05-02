-- Serialises state.char.affects to bridge/buffs.state (JSON) whenever
-- affects_changed fires. Installed on top of affects.lua's hooks so that
-- _load_active() results are in the file before the first render tick.
--
-- Atomic write: buffs.state.tmp → os.rename → buffs.state.

local json       = require("dkjson")
local STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/buffs.state"
local TMP_PATH   = STATE_PATH .. ".tmp"

local function serialize()
    local affects = state.char.affects or {}
    local out = {}
    for _, e in ipairs(affects) do
        out[#out + 1] = {
            name       = e.name,
            type       = e.type or json.null,
            expires_at = e.expires_at or json.null,
        }
    end
    local ok, encoded = pcall(json.encode, out)
    if not ok then
        dbg("[BUFFS_STATE] encode failed: " .. tostring(encoded))
        return
    end
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[BUFFS_STATE] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, STATE_PATH)
end

-- Fire on every affect change.
events.subscribe("affects_changed", serialize)

-- Wrap state.char.reset so disconnect blanks the pane within one poll tick.
local _orig_reset = state.char.reset
---@diagnostic disable-next-line: duplicate-set-field
state.char.reset = function()
    if _orig_reset then _orig_reset() end
    serialize()
end

-- Wrap _affects_register_triggers so our Char.Name wrapper is installed
-- AFTER affects.lua's (which runs _load_active). This ensures serialize()
-- sees the final loaded state, including the empty-list case that emits no
-- affects_changed.
local _orig_register = _affects_register_triggers
function _affects_register_triggers()
    _orig_register()
    local _orig_name = gmcp.handlers["Char.Name"]
    gmcp.handlers["Char.Name"] = function(body)
        if _orig_name then _orig_name(body) end
        serialize()
    end
end

-- Initial write so the renderer has a file on first start.
serialize()

dbg("[BUFFS_STATE] loaded")
