-- Serialises state.group.members to bridge/runtime/group.state (JSON)
-- whenever group_changed or char_reset fires.
--
-- Atomic write: group.state.tmp → os.rename → group.state.

local json       = require("dkjson")
local STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/runtime/group.state"
local TMP_PATH   = STATE_PATH .. ".tmp"

local function pct_pair(kind, val, maxv, str)
    local pct, known = state.group.pct_for(kind, val, maxv, str)
    if pct == nil then return json.null, json.null end
    return pct, known
end

local function serialize()
    local members_out = {}
    for _, m in pairs(state.group.members) do
        local hp_pct,   hp_known   = pct_pair("hp",   m.hp,   m.maxhp,   m.hp_string)
        local mana_pct, mana_known = pct_pair("mana", m.mana, m.maxmana, m.mana_string)
        local mp_pct,   mp_known   = pct_pair("mp",   m.mp,   m.maxmp,   m.mp_string)

        members_out[#members_out + 1] = {
            id          = m.id          or json.null,
            type        = m.type        or json.null,
            name        = m.name        or json.null,
            hp          = m.hp          or json.null,
            maxhp       = m.maxhp       or json.null,
            hp_string   = m.hp_string   or json.null,
            hp_pct      = hp_pct,
            hp_known    = hp_known,
            mana        = m.mana        or json.null,
            maxmana     = m.maxmana     or json.null,
            mana_string = m.mana_string or json.null,
            mana_pct    = mana_pct,
            mana_known  = mana_known,
            mp          = m.mp          or json.null,
            maxmp       = m.maxmp       or json.null,
            mp_string   = m.mp_string   or json.null,
            mp_pct      = mp_pct,
            mp_known    = mp_known,
        }
    end

    table.sort(members_out, function(a, b)
        local ia = type(a.id) == "number" and a.id or math.huge
        local ib = type(b.id) == "number" and b.id or math.huge
        return ia < ib
    end)

    local payload = { members = members_out }
    local ok, encoded = pcall(json.encode, payload)
    if not ok then
        dbg("[GROUP_SERIALIZER] encode failed: " .. tostring(encoded))
        return
    end
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[GROUP_SERIALIZER] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, STATE_PATH)
end

events.subscribe("group_changed", serialize)
events.subscribe("char_reset",    serialize)

serialize()

dbg("[GROUP_SERIALIZER] loaded")
