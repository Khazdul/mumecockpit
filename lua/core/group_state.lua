-- Always-on GMCP collector for Group.Set / Group.Add / Group.Update / Group.Remove.
-- Primary writer for state.group.*; no alias, no register_script.

local _band = {
    hp = {
        dying    = 0.0,
        awful    = 0.05,
        bad      = 0.18,
        wounded  = 0.35,
        hurt     = 0.58,
        fine     = 0.85,
        healthy  = 1.0,
    },
    mana = {
        frozen   = 0.0,
        icy      = 0.05,
        cold     = 0.18,
        warm     = 0.35,
        hot      = 0.58,
        burning  = 0.85,
        full     = 1.0,
    },
    mp = {
        exhausted  = 0.0,
        fainting   = 0.13,
        weak       = 0.38,
        slow       = 0.63,
        tired      = 0.88,
        unwearied  = 1.0,
    },
}

-- Explicit field projection: GMCP kebab-case key → snake_case state key.
local _field_map = {
    ["id"]          = "id",
    ["type"]        = "type",
    ["name"]        = "name",
    ["hp"]          = "hp",
    ["hp-string"]   = "hp_string",
    ["maxhp"]       = "maxhp",
    ["mana"]        = "mana",
    ["mana-string"] = "mana_string",
    ["maxmana"]     = "maxmana",
    ["mp"]          = "mp",
    ["mp-string"]   = "mp_string",
    ["maxmp"]       = "maxmp",
}

-- ── state.group ──────────────────────────────────────────────────────────────

state.group = {
    members = {},
}

function state.group.reset()
    for k in pairs(state.group.members) do
        state.group.members[k] = nil
    end
    events.emit("group_changed")
end

-- Returns (pct, known, label).
--   known=true  → computed from value/maxv; pct is in [0,1].
--   known=false → looked up from band table or nil if unrecognised.
function state.group.pct_for(kind, value, maxv, str)
    if type(value) == "number" and type(maxv) == "number" and maxv > 0 then
        return math.max(0, math.min(1, value / maxv)), true, str
    end
    local tbl = _band[kind]
    if tbl and str ~= nil then
        local v = tbl[str]
        if v ~= nil then
            return v, false, str
        end
    end
    return nil, false, str
end

-- ── GMCP handlers ────────────────────────────────────────────────────────────

gmcp.handlers["Group.Set"] = function(body)
    if body == nil or type(body) ~= "table" then
        dbg("[GROUP] Set: unexpected payload " .. tostring(body))
        return
    end

    local old_ids = {}
    for id in pairs(state.group.members) do
        old_ids[id] = true
    end

    for k in pairs(state.group.members) do
        state.group.members[k] = nil
    end

    local new_ids = {}
    for _, entry in ipairs(body) do
        if entry.type == "npc" or entry.type == "you" then
            -- silently excluded
        else
            if entry.type ~= "ally" then
                dbg("[GROUP] unknown member type in Set: " .. tostring(entry.type))
            end
            local member = {}
            for gmcp_key, state_key in pairs(_field_map) do
                local v = entry[gmcp_key]
                if v ~= nil and v ~= gmcp.null then
                    member[state_key] = v
                end
            end
            state.group.members[member.id] = member
            new_ids[member.id] = true
        end
    end

    for id in pairs(old_ids) do
        if not new_ids[id] then
            events.emit("group_member_removed", id)
        end
    end
    for id in pairs(new_ids) do
        if not old_ids[id] then
            events.emit("group_member_added", state.group.members[id])
        end
    end

    events.emit("group_changed")
end

gmcp.handlers["Group.Add"] = function(body)
    body = body or {}
    if body.type == "npc" or body.type == "you" then return end
    if body.type ~= "ally" then
        dbg("[GROUP] unknown member type in Add: " .. tostring(body.type))
    end

    local member = {}
    for gmcp_key, state_key in pairs(_field_map) do
        local v = body[gmcp_key]
        if v ~= nil and v ~= gmcp.null then
            member[state_key] = v
        end
    end

    state.group.members[member.id] = member
    events.emit("group_member_added", member)
    events.emit("group_changed")
end

gmcp.handlers["Group.Update"] = function(body)
    body = body or {}
    local existing = state.group.members[body.id]
    if existing == nil then
        dbg("[GROUP] update for unknown id " .. tostring(body.id) .. ", ignoring")
        return
    end

    for gmcp_key, state_key in pairs(_field_map) do
        local v = body[gmcp_key]
        if v ~= nil then
            existing[state_key] = (v ~= gmcp.null) and v or nil
        end
    end

    events.emit("group_member_updated", existing)
    events.emit("group_changed")
end

gmcp.handlers["Group.Remove"] = function(body)
    local id = tonumber(body)
    if id == nil then
        dbg("[GROUP] Remove: expected integer payload, got " .. tostring(body))
        return
    end
    state.group.members[id] = nil
    events.emit("group_member_removed", id)
    events.emit("group_changed")
end

-- ── reset on disconnect ───────────────────────────────────────────────────────

events.subscribe("char_reset", function() state.group.reset() end)

dbg("[GROUP_STATE] loaded")
