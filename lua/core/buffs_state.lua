-- Serialises state.char.affects and state.char.stored_spells to
-- bridge/buffs.state (JSON) whenever affects_changed, stored_spells_changed,
-- char_reset, or gmcp_char_name fires.
--
-- Atomic write: buffs.state.tmp → os.rename → buffs.state.

local json       = require("dkjson")
local STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/buffs.state"
local TMP_PATH   = STATE_PATH .. ".tmp"

local function serialize()
    local affects = state.char.affects or {}
    local affects_out = {}
    for _, e in ipairs(affects) do
        affects_out[#affects_out + 1] = {
            name              = e.name,
            type              = e.type or json.null,
            expires_at        = e.expires_at or json.null,
            expected_duration = e.expected_duration or json.null,
        }
    end

    local stored_spells = state.char.stored_spells or {}
    local stored_out = {}
    for _, e in ipairs(stored_spells) do
        stored_out[#stored_out + 1] = {
            name              = e.name,
            expires_at        = e.tracked and e.expires_at or json.null,
            expected_duration = e.tracked and e.expected_duration or json.null,
            tracked           = e.tracked,
        }
    end

    local payload = { affects = affects_out, stored_spells = stored_out }
    local ok, encoded = pcall(json.encode, payload)
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

-- Fire on every affect or stored-spell change, reset, or new character name.
-- affects.lua subscribes to gmcp_char_name before this file (alphabetical),
-- so _load_active() results are in state.char.affects when our subscriber runs.
events.subscribe("affects_changed",        serialize)
events.subscribe("stored_spells_changed",  serialize)
events.subscribe("char_reset",             function() serialize() end)
events.subscribe("gmcp_char_name",         function() serialize() end)

-- Initial write so the renderer has a file on first start.
serialize()

dbg("[BUFFS_STATE] loaded")
