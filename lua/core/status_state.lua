-- Serialises state.char.* to bridge/status.state (JSON) whenever any
-- Char.Name, Char.StatusVars, or Char.Vitals payload arrives.
--
-- Approach: wrap char_state's existing handlers from here (load order is
-- alphabetical, so char_state loads first). Each wrapper calls the original
-- handler then re-serialises. This keeps char_state.lua clean — no callback
-- list or modifications needed there.
--
-- Atomic write: status.state.tmp → os.rename → status.state so the Python
-- reader never sees a partial file.

local json = require("dkjson")
local STATE_PATH  = os.getenv("HOME") .. "/MUME/bridge/status.state"
local TMP_PATH    = STATE_PATH .. ".tmp"
local LAYOUT_PATH = os.getenv("HOME") .. "/MUME/bridge/layout.conf"

local _last_height = nil

local function fmt_num(n)
    if type(n) ~= "number" then return n end
    -- insert comma separators: 232200 → "232,200"
    local s = tostring(math.floor(n))
    return s:reverse():gsub("(%d%d%d)", "%1,"):reverse():gsub("^,", "")
end

local function serialize()
    local c = state.char

    -- sneak: null|"s"|"S" → off/on
    local sneak_val = "off"
    if c.sneak and c.sneak ~= json.null then
        sneak_val = "on"
    end

    -- climb: null|"c"|"C" → off/on
    local climb_val = "off"
    if c.climb and c.climb ~= json.null then
        climb_val = "on"
    end

    -- swim: bool → on/off
    local swim_val = "off"
    if c.swim then swim_val = "on" end

    local now = os.time()
    local list = {}
    for _, a in ipairs(state.char.affects or {}) do
        local remaining
        if a.expires_at then
            remaining = a.expires_at - now
            if remaining < 0 then remaining = 0 end
        end
        list[#list + 1] = {
            name              = a.name,
            type              = a.type,
            remaining_seconds = remaining,
        }
    end
    table.sort(list, function(x, y)
        local xr = x.remaining_seconds
        local yr = y.remaining_seconds
        if xr == nil and yr == nil then return x.name < y.name end
        if xr == nil then return false end
        if yr == nil then return true end
        if xr ~= yr then return xr < yr end
        return x.name < y.name
    end)

    local payload = {
        character   = c.name,
        level       = c.level,
        xp          = c.xp,
        tp          = c.tp,
        session_xp  = state.session and state.session.session_xp or nil,
        session_tp  = state.session and state.session.session_tp or nil,
        mood        = c.mood,
        alertness   = c.alertness,
        sneak       = sneak_val,
        position    = c.position,
        climb       = climb_val,
        swim        = swim_val,
        game_time   = state.world.clock and state.world.clock.format("panel") or nil,
        affects     = list,
    }

    local encoded = json.encode(payload)
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[STATUS_STATE] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, STATE_PATH)

    local n = #list
    local new_height = 11 + math.max(1, n)
    if new_height ~= _last_height then
        local conf_lines = {}
        local found = false
        local lf = io.open(LAYOUT_PATH, "r")
        if lf then
            for line in lf:lines() do
                if line:match("^status_height=") then
                    conf_lines[#conf_lines + 1] = "status_height=" .. new_height
                    found = true
                else
                    conf_lines[#conf_lines + 1] = line
                end
            end
            lf:close()
        end
        if not found then
            conf_lines[#conf_lines + 1] = "status_height=" .. new_height
        end
        local ltmp = LAYOUT_PATH .. ".tmp"
        local lf2 = io.open(ltmp, "w")
        if lf2 then
            lf2:write(table.concat(conf_lines, "\n") .. "\n")
            lf2:close()
            os.rename(ltmp, LAYOUT_PATH)
        end
        tintin_cmd("gts", "#system {bash bridge/apply_layout.sh}")
        _last_height = new_height
    end
end

-- Wrap handlers: call original first, then serialize.
local _orig_name    = gmcp.handlers["Char.Name"]
local _orig_vars    = gmcp.handlers["Char.StatusVars"]
local _orig_vitals  = gmcp.handlers["Char.Vitals"]
local _orig_reset   = state.char.reset

gmcp.handlers["Char.Name"] = function(body)
    if _orig_name then _orig_name(body) end
    serialize()
end

gmcp.handlers["Char.StatusVars"] = function(body)
    if _orig_vars then _orig_vars(body) end
    serialize()
end

gmcp.handlers["Char.Vitals"] = function(body)
    if _orig_vitals then _orig_vitals(body) end
    serialize()
end

---@diagnostic disable-next-line: duplicate-set-field
state.char.reset = function()
    if _orig_reset then _orig_reset() end
    serialize()
end

events.subscribe("clock_changed",   function() serialize() end)
events.subscribe("affects_changed", function() serialize() end)

dbg("[STATUS_STATE] loaded")
