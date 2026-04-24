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
local STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/status.state"
local TMP_PATH   = STATE_PATH .. ".tmp"

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

    local payload = {
        character   = c.name,
        level       = c.level,
        xp          = c.xp,
        tp          = c.tp,
        session_xp  = nil,
        session_tp  = nil,
        mood        = c.mood,
        alertness   = c.alertness,
        sneak       = sneak_val,
        position    = c.position,
        climb       = climb_val,
        swim        = swim_val,
        carrying    = c.carrying,
        game_time   = nil,
        affects     = {},
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
end

-- Wrap handlers: call original first, then serialize.
local _orig_name    = gmcp.handlers["Char.Name"]
local _orig_vars    = gmcp.handlers["Char.StatusVars"]
local _orig_vitals  = gmcp.handlers["Char.Vitals"]

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

dbg("[STATUS_STATE] loaded")
