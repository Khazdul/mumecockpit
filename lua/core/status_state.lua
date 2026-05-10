-- Serialises state.char.* to bridge/runtime/status.state (JSON) whenever
-- Char.Name, Char.StatusVars, Char.Vitals, or char_reset fires.
-- Subscribes to the gmcp_* events emitted by dispatch after the primary
-- writers in char_state.lua have updated state.char.*.
--
-- Atomic write: status.state.tmp → os.rename → status.state so the Python
-- reader never sees a partial file.

local json = require("dkjson")
local STATE_PATH  = os.getenv("HOME") .. "/MUME/bridge/runtime/status.state"
local TMP_PATH    = STATE_PATH .. ".tmp"
local LAYOUT_PATH = os.getenv("HOME") .. "/MUME/bridge/runtime/layout.conf"

-- 6 rows (2 progress-bar rows + 1 toggle row + 1 blank + 2 data rows). Bump when rows are added in bridge/panes/status_pane.py.
local STATIC_ROWS = 6

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

    -- ride: null|false|json.null → off, anything else → on
    local ride_val = "off"
    if c.ride and c.ride ~= json.null then
        ride_val = "on"
    end

    -- swim: bool → on/off
    local swim_val = "off"
    if c.swim then swim_val = "on" end

    local nt = state.world.clock and state.world.clock.next_transition() or nil
    local payload = {
        character      = c.name,
        race           = c.race,
        level          = c.level,
        wimpy          = c.wimpy,
        xp             = c.xp,
        tp             = c.tp,
        xp_progress    = level_progress.compute_xp_progress(c.level, c.xp),
        tp_progress    = level_progress.compute_tp_progress(c.level, c.tp, c.race),
        run_xp         = state.run and state.run.xp or nil,
        run_tp         = state.run and state.run.tp or nil,
        mood           = c.mood,
        alertness      = c.alertness,
        sneak          = sneak_val,
        ride           = ride_val,
        position       = c.position,
        climb          = climb_val,
        swim           = swim_val,
        game_time      = state.world.clock and state.world.clock.format("panel_time") or nil,
        time_period        = nt and nt.period    or nil,
        time_transition_at = nt and nt.at        or nil,
        time_precision     = nt and nt.precision or nil,
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

    local new_height = STATIC_ROWS
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
        tintin_cmd("gts", "#system {bash bridge/layout/apply_layout.sh}")
        _last_height = new_height
    end
end

events.subscribe("gmcp_char_name",        function() serialize() end)
events.subscribe("gmcp_char_status_vars", function() serialize() end)
events.subscribe("gmcp_char_vitals",      function() serialize() end)
events.subscribe("char_reset",            function() serialize() end)
events.subscribe("clock_changed",         function() serialize() end)

dbg("[STATUS_STATE] loaded")
