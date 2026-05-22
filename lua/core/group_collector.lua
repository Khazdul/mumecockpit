-- Always-on GMCP collector and primary writer for state.group.*.
-- Populates from Group.Set / Group.Add / Group.Update / Group.Remove.
-- No alias, no metadata header. Pair with lua/core/group_state.lua (serializer).

local _band = {
    hp = {
        dying   = {0,   0},
        awful   = {1,   10},
        bad     = {11,  25},
        wounded = {26,  45},
        hurt    = {46,  70},
        fine    = {71,  99},
        healthy = {100, 100},
    },
    mana = {
        frozen  = {0,   0},
        icy     = {1,   10},
        cold    = {11,  25},
        warm    = {26,  45},
        hot     = {46,  70},
        burning = {71,  99},
        full    = {100, 100},
    },
    mp = {
        -- placeholder ranges; calibrate against server once data is available
        exhausted = {0,   0},
        fainting  = {1,   25},
        weak      = {26,  50},
        slow      = {51,  75},
        tired     = {76,  99},
        unwearied = {100, 100},
    },
}

-- Explicit field projection: GMCP kebab-case key → snake_case state key.
local _field_map = {
    ["id"]          = "id",
    ["type"]        = "type",
    ["name"]        = "name",
    ["label"]       = "label",
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

-- Vital pairs: value + string fields managed by freshness inference in Group.Update.
local _vital_pairs = {
    { gmcp_value = "hp",   gmcp_str = "hp-string",   gmcp_maxv = "maxhp",
      key_value  = "hp",   key_str  = "hp_string",   key_maxv  = "maxhp",   kind = "hp" },
    { gmcp_value = "mana", gmcp_str = "mana-string", gmcp_maxv = "maxmana",
      key_value  = "mana", key_str  = "mana_string", key_maxv  = "maxmana", kind = "mana" },
    { gmcp_value = "mp",   gmcp_str = "mp-string",   gmcp_maxv = "maxmp",
      key_value  = "mp",   key_str  = "mp_string",   key_maxv  = "maxmp",   kind = "mp" },
}

-- Keys handled by vital-pair inference; skipped in the direct-apply loop.
local _vital_skip = {
    ["hp"] = true, ["hp-string"] = true,
    ["mana"] = true, ["mana-string"] = true,
    ["mp"] = true, ["mp-string"] = true,
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
--   known=false → midpoint of band range; nil pct if label unrecognised.
function state.group.pct_for(kind, value, maxv, str)
    if type(value) == "number" and type(maxv) == "number" and maxv > 0 then
        return math.max(0, math.min(1, value / maxv)), true, str
    end
    local tbl = _band[kind]
    if tbl and str ~= nil then
        local range = tbl[str]
        if range ~= nil then
            return (range[1] + range[2]) / 200, false, str
        end
    end
    return nil, false, str
end

-- Returns true  if pct_int ∈ [lo,hi] of label's band (inclusive).
-- Returns false if pct_int is outside the band (contradiction).
-- Returns nil   if label is not in the band table (unknown; forward-compat).
function state.group.in_band(kind, pct_int, label)
    local tbl = _band[kind]
    if tbl == nil then return nil end
    local range = tbl[label]
    if range == nil then return nil end
    return pct_int >= range[1] and pct_int <= range[2]
end

-- ── helpers ───────────────────────────────────────────────────────────────────

-- MUME sends the label field on every NPC member: integer 0 when unlabeled,
-- non-empty string once labeled. A label counts as present only when it is a
-- non-empty string.
local function _is_label(v)
    return type(v) == "string" and v ~= ""
end

-- Exclude "you" and unlabeled NPCs; labeled NPCs (key NPCs, mercenaries) are
-- in. See ADR 0094.
local function _should_include(entry)
    local t = entry.type
    if t == "you" then return false end
    if t == "npc" and not _is_label(entry.label) then return false end
    return true
end

local function _warn_unknown_type(t)
    if t ~= "ally" and t ~= "npc" and t ~= "you" then
        dbg("[GROUP] unknown member type: " .. tostring(t))
    end
end

-- ── GMCP handlers ────────────────────────────────────────────────────────────

gmcp.handlers["Group.Set"] = function(body)
    if body == nil or type(body) ~= "table" then
        dbg("[GROUP] Set: unexpected payload " .. tostring(body))
        return
    end

    local old_ids = {}
    for id in pairs(state.group.members) do old_ids[id] = true end
    for k in pairs(state.group.members) do state.group.members[k] = nil end

    local new_ids = {}
    for _, entry in ipairs(body) do
        _warn_unknown_type(entry.type)
        if _should_include(entry) then
            local member = {}
            for gmcp_key, state_key in pairs(_field_map) do
                local v = entry[gmcp_key]
                if v ~= nil and v ~= gmcp.null then member[state_key] = v end
            end
            if not _is_label(member.label) then member.label = nil end
            state.group.members[member.id] = member
            new_ids[member.id] = true
        end
    end

    for id in pairs(old_ids) do
        if not new_ids[id] then events.emit("group_member_removed", id) end
    end
    for id in pairs(new_ids) do
        if not old_ids[id] then events.emit("group_member_added", state.group.members[id]) end
    end
    events.emit("group_changed")
end

gmcp.handlers["Group.Add"] = function(body)
    body = body or {}
    _warn_unknown_type(body.type)
    if not _should_include(body) then return end

    local member = {}
    for gmcp_key, state_key in pairs(_field_map) do
        local v = body[gmcp_key]
        if v ~= nil and v ~= gmcp.null then member[state_key] = v end
    end
    if not _is_label(member.label) then member.label = nil end
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

    -- Direct-apply: non-vital fields and maxv.
    -- maxv is applied before vital-pair inference so pct checks use the fresh max.
    for gmcp_key, state_key in pairs(_field_map) do
        if not _vital_skip[gmcp_key] then
            local v = body[gmcp_key]
            if v ~= nil then
                existing[state_key] = (v ~= gmcp.null) and v or nil
            end
        end
    end

    -- Vital pairs: freshness inference per pair.
    for _, pair in ipairs(_vital_pairs) do
        local val_raw = body[pair.gmcp_value]
        local str_raw = body[pair.gmcp_str]
        local has_value = val_raw ~= nil
        local has_str   = str_raw ~= nil

        if not has_value and not has_str then
            -- Neither field in payload; nothing to do for this pair.
        elseif has_value and has_str then
            -- Case A: both present; no inference needed.
            existing[pair.key_value] = (val_raw ~= gmcp.null) and val_raw or nil
            existing[pair.key_str]   = (str_raw ~= gmcp.null) and str_raw or nil
        elseif has_value then
            -- Case B: value only; cached string referred to the previous pct.
            existing[pair.key_value] = (val_raw ~= gmcp.null) and val_raw or nil
            existing[pair.key_str]   = nil
        else
            -- Case C: string only; check band consistency with cached value.
            local str = (str_raw ~= gmcp.null) and str_raw or nil
            local cached_val = existing[pair.key_value]
            local cached_max = existing[pair.key_maxv]
            if cached_val ~= nil and cached_max ~= nil and cached_max > 0 then
                local pct_int = math.floor(100 * cached_val / cached_max)
                local check = state.group.in_band(pair.kind, pct_int, str)
                if check == false then
                    existing[pair.key_value] = nil
                elseif check == nil then
                    dbg("[GROUP] unknown " .. pair.kind .. " label: " .. tostring(str))
                end
            end
            existing[pair.key_str] = str
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
    if state.group.members[id] == nil then
        return
    end
    state.group.members[id] = nil
    events.emit("group_member_removed", id)
    events.emit("group_changed")
end

-- ── reset on disconnect ───────────────────────────────────────────────────────

events.subscribe("char_reset", function() state.group.reset() end)

dbg("[GROUP] loaded")
