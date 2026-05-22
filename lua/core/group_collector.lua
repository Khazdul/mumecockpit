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
        hot     = {46,  75},
        burning = {76,  99},
        full    = {100, 100},
    },
    mp = {
        exhausted = {0,   0},
        fainting  = {1,   4},
        weak      = {5,   14},
        slow      = {15,  29},
        tired     = {30,  49},
        rested    = {50,  69},
        steadfast = {70,  99},
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
local _hp_pair = {
    gmcp_value = "hp",   gmcp_str = "hp-string",   gmcp_maxv = "maxhp",
    key_value  = "hp",   key_str  = "hp_string",   key_maxv  = "maxhp",   kind = "hp",
}
local _vital_pairs = {
    _hp_pair,
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

-- Holding pen for type:"npc" members that arrive (or become) unlabeled.
-- Promoted into state.group.members if a later Group.Update gives them a
-- label; demoted back here if a labeled NPC is unlabeled again. Not part of
-- the public state.group surface — the renderer only sees members.
local _excluded = {}

-- ── state.group ──────────────────────────────────────────────────────────────

state.group = {
    members = {},
}

function state.group.reset()
    for k in pairs(state.group.members) do
        state.group.members[k] = nil
    end
    for k in pairs(_excluded) do
        _excluded[k] = nil
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
-- non-empty string once labeled. Normalise to either a non-empty string or
-- nil so a labeled-NPC check is just `member.label ~= nil`. Members must
-- never carry label = 0, "", or gmcp.null.
local function _norm_label(v)
    if type(v) == "string" and v ~= "" then return v end
    return nil
end

local function _warn_unknown_type(t)
    if t ~= "ally" and t ~= "npc" and t ~= "you" then
        dbg("[GROUP] unknown member type: " .. tostring(t))
    end
end

-- Classify a projected member after _norm_label has been applied. See
-- ADR 0094. Unknown types fall through to "include" (parity with prior
-- behaviour).
--   "drop"    → type "you"; not stored anywhere.
--   "exclude" → type "npc" without a label; goes to _excluded.
--   "include" → goes to state.group.members.
local function _classify(member)
    if member.type == "you" then return "drop" end
    if member.type == "npc" and member.label == nil then return "exclude" end
    return "include"
end

-- Case C of ADR 0052: apply a string-only vital update onto a member.
-- If cached value/max allow a percentage, check it against the band of the
-- new label; clear a contradictory value. Always store the string (may be
-- nil to clear). Used by Group.Update and by the Char.Vitals
-- buffer/opponent cross-application.
local function _apply_string_only(member, pair, str)
    local cached_val = member[pair.key_value]
    local cached_max = member[pair.key_maxv]
    if cached_val ~= nil and cached_max ~= nil and cached_max > 0 then
        local pct_int = math.floor(100 * cached_val / cached_max)
        local check = state.group.in_band(pair.kind, pct_int, str)
        if check == false then
            member[pair.key_value] = nil
        elseif check == nil then
            dbg("[GROUP] unknown " .. pair.kind .. " label: " .. tostring(str))
        end
    end
    member[pair.key_str] = str
end

-- Project a GMCP entry into a member object, applying _norm_label so the
-- label field is either a non-empty string or nil.
local function _project(body)
    local member = {}
    for gmcp_key, state_key in pairs(_field_map) do
        local v = body[gmcp_key]
        if v ~= nil and v ~= gmcp.null then member[state_key] = v end
    end
    member.label = _norm_label(member.label)
    return member
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
    for k in pairs(_excluded) do _excluded[k] = nil end

    local new_ids = {}
    for _, entry in ipairs(body) do
        _warn_unknown_type(entry.type)
        local member = _project(entry)
        local where = _classify(member)
        if where == "include" then
            state.group.members[member.id] = member
            new_ids[member.id] = true
        elseif where == "exclude" then
            _excluded[member.id] = member
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

    local member = _project(body)
    local where = _classify(member)
    if where == "drop" then return end
    if where == "exclude" then
        _excluded[member.id] = member
        return
    end

    state.group.members[member.id] = member
    events.emit("group_member_added", member)
    events.emit("group_changed")
end

gmcp.handlers["Group.Update"] = function(body)
    body = body or {}
    local id = body.id
    local existing = state.group.members[id]
    local was_in_members = existing ~= nil
    if existing == nil then existing = _excluded[id] end
    if existing == nil then
        dbg("[GROUP] update for unknown id " .. tostring(id) .. ", ignoring")
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
    existing.label = _norm_label(existing.label)

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
            _apply_string_only(existing, pair, str)
        end
    end

    -- Re-evaluate inclusion. A promotion/demotion emits exactly one
    -- membership event; a plain in-place update emits group_member_updated.
    local has_label = existing.label ~= nil
    local is_npc    = existing.type == "npc"

    if not was_in_members and has_label then
        _excluded[id] = nil
        state.group.members[id] = existing
        events.emit("group_member_added", existing)
    elseif was_in_members and is_npc and not has_label then
        state.group.members[id] = nil
        _excluded[id] = existing
        events.emit("group_member_removed", id)
    elseif was_in_members then
        events.emit("group_member_updated", existing)
    end
    -- excluded → excluded: no membership event.

    events.emit("group_changed")
end

gmcp.handlers["Group.Remove"] = function(body)
    local id = tonumber(body)
    if id == nil then
        dbg("[GROUP] Remove: expected integer payload, got " .. tostring(body))
        return
    end
    if state.group.members[id] ~= nil then
        state.group.members[id] = nil
        _excluded[id] = nil
        events.emit("group_member_removed", id)
        events.emit("group_changed")
    elseif _excluded[id] ~= nil then
        _excluded[id] = nil
    end
end

-- ── Char.Vitals cross-update: buffer / opponent HP ───────────────────────────
--
-- Mid-fight, MUME delivers a group member's HP changes through Char.Vitals
-- rather than Group.Update: at fight start the packet carries identity
-- strings (buffer / opponent) plus HP band strings (buffer-hits /
-- opponent-hits); subsequent packets carry only the *-hits values. To keep
-- the group pane live we cache the latest identity strings here and, on
-- every *-hits packet, resolve them against state.group.members and apply
-- the band string as that member's hp_string via Case C of ADR 0052.

local _buffer
local _opponent

-- Resolve a buffer/opponent identity string to a member of
-- state.group.members. The string can take several forms — NPC
-- "<description> (LABEL)", unlabeled ally "<Name>", or labeled ally as
-- bare label, bare name, or "<Name> (LABEL)" — so we build a candidate
-- token set and match case-insensitively against each member's label
-- (preferred) and name. Returns the matched member or nil.
local function _resolve_identity(ident)
    if type(ident) ~= "string" or ident == "" then return nil end

    local tokens = { ident:lower() }
    local before, paren = ident:match("^(.-)%s*%(([^()]+)%)%s*$")
    if paren then
        tokens[#tokens+1] = paren:lower()
        if before and before ~= "" then
            tokens[#tokens+1] = before:lower()
        end
    end

    for _, member in pairs(state.group.members) do
        if member.label then
            local mlabel = member.label:lower()
            for _, t in ipairs(tokens) do
                if t == mlabel then return member end
            end
        end
    end
    for _, member in pairs(state.group.members) do
        if member.name then
            local mname = member.name:lower()
            for _, t in ipairs(tokens) do
                if t == mname then return member end
            end
        end
    end
    return nil
end

events.subscribe("gmcp_char_vitals", function(body)
    if type(body) ~= "table" then return end

    -- Identity strings persist across the partial packets that follow.
    -- Resolution to a member happens fresh on every *-hits packet —
    -- members come and go (room-scoped), so a cached reference would
    -- go stale.
    if body.buffer ~= nil then
        _buffer = (body.buffer ~= gmcp.null) and body.buffer or nil
    end
    if body.opponent ~= nil then
        _opponent = (body.opponent ~= gmcp.null) and body.opponent or nil
    end

    local changed
    local buf_hits = body["buffer-hits"]
    if buf_hits ~= nil and buf_hits ~= gmcp.null then
        local m = _resolve_identity(_buffer)
        if m then
            _apply_string_only(m, _hp_pair, buf_hits)
            changed = changed or {}
            changed[m] = true
        end
    end
    local opp_hits = body["opponent-hits"]
    if opp_hits ~= nil and opp_hits ~= gmcp.null then
        local m = _resolve_identity(_opponent)
        if m then
            _apply_string_only(m, _hp_pair, opp_hits)
            changed = changed or {}
            changed[m] = true
        end
    end

    if changed then
        for m in pairs(changed) do
            events.emit("group_member_updated", m)
        end
        events.emit("group_changed")
    end
end)

-- ── reset on disconnect ───────────────────────────────────────────────────────

events.subscribe("char_reset", function()
    _buffer = nil
    _opponent = nil
    state.group.reset()
end)

events.subscribe("run_started", function()
    _buffer = nil
    _opponent = nil
end)

dbg("[GROUP] loaded")
