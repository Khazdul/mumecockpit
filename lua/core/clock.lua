-- Passive game-time clock. Single-anchor model after MMapper:
-- mume_start_epoch is the only persisted state; current time is computed on demand.
-- Three sync sources on the event bus: event_sun, mume_time_line, room_clock_line.
-- Persists to bridge/clock.state. Drives status-pane Phase 3.

local CLOCK_STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/clock.state"
local TMP_PATH         = CLOCK_STATE_PATH .. ".tmp"

-- Derived from: year 2850 month 0 day 0 hour 0 = unix 1696118400
-- (MUME server reset, ~October 1 2023). First real sync overwrites this.
local SEED_EPOCH = 218678400   -- = 1696118400 - 2850 * 518400

-- Precision levels (ordered so < / >= comparisons work)
local P = { UNSET = 0, DAY = 1, HOUR = 2, MINUTE = 3 }
local P_NAME = { [0] = "UNSET", [1] = "DAY", [2] = "HOUR", [3] = "MINUTE" }

-- Calendar tables (MMapper g_dawnHour / g_duskHour), Lua 1-indexed, month 0→index 1
local dawn = { 8, 9, 8, 7, 7, 6, 5, 4, 5, 6, 7, 7 }
local dusk  = {18,17,18,19,20,20,21,22,21,20,20,19}

local westron_months = {
    ["Afteryule"]=0,  ["Solmath"]=1,   ["Rethe"]=2,      ["Astron"]=3,
    ["Thrimidge"]=4,  ["Forelithe"]=5, ["Afterlithe"]=6, ["Wedmath"]=7,
    ["Halimath"]=8,   ["Winterfilth"]=9, ["Blotmath"]=10, ["Foreyule"]=11,
}
local sindarin_months = {
    ["Narwain"]=0, ["Ninui"]=1,    ["Gwaeron"]=2,  ["Gwirith"]=3,
    ["Lothron"]=4, ["Norui"]=5,    ["Cerveth"]=6,  ["Urui"]=7,
    ["Ivanneth"]=8, ["Narbeleth"]=9, ["Hithui"]=10, ["Girithron"]=11,
}
local month_name = {
    [0]="Afteryule", [1]="Solmath",   [2]="Rethe",     [3]="Astron",
    [4]="Thrimidge", [5]="Forelithe", [6]="Afterlithe", [7]="Wedmath",
    [8]="Halimath",  [9]="Winterfilth", [10]="Blotmath", [11]="Foreyule",
}
local weekday_name = {
    [0]="Sterday", [1]="Sunday", [2]="Monday", [3]="Trewsday",
    [4]="Hevensday", [5]="Mersday", [6]="Highday",
}
-- season by month index 0-11 (1-indexed for Lua array)
local season = {
    "Winter","Winter","Spring","Spring","Spring","Summer",
    "Summer","Summer","Autumn","Autumn","Autumn","Winter",
}

-- Module state table — exposed as state.world.clock
local C = {
    mume_start_epoch  = SEED_EPOCH,
    last_sync_epoch   = nil,
    last_sync_reason  = nil,
    precision         = P.UNSET,
    _last_emitted_minute = nil,
}
state.world.clock = C

-- ---------------------------------------------------------------------------
-- Internal helpers
-- ---------------------------------------------------------------------------

local function _total_seconds(year, month, day0, hour, minute)
    -- day0 = day number − 1 (0-indexed from start of month)
    return year * 518400 + month * 43200 + day0 * 1440 + hour * 60 + minute
end

local function _compute_moment()
    local elapsed = os.time() - C.mume_start_epoch
    if elapsed < 0 then elapsed = 0 end
    local min_part  = elapsed % 60
    local hour_part = math.floor(elapsed / 60) % 24
    local day0      = math.floor(elapsed / 1440) % 30
    local mon       = math.floor(elapsed / 43200) % 12
    local yr        = math.floor(elapsed / 518400)
    local total_days = math.floor(elapsed / 1440)
    local wd        = total_days % 7
    local tod
    if hour_part >= dawn[mon+1] and hour_part < dusk[mon+1] then
        tod = "day"
    elseif hour_part == dusk[mon+1] then
        tod = "dusk"
    elseif hour_part < dawn[mon+1] and hour_part >= dawn[mon+1] - 1 then
        tod = "dawn"
    else
        tod = "night"
    end
    return {
        year        = yr,
        month       = mon,
        day         = day0 + 1,
        hour        = hour_part,
        minute      = min_part,
        weekday     = wd,
        season      = season[mon + 1],
        time_of_day = tod,
        precision   = P_NAME[C.precision],
    }
end

local function _parse_month(name)
    return westron_months[name] or sindarin_months[name]
end

local function _parse_day(s)
    return tonumber(s:match("^(%d+)"))
end

local function _parse_hour24(h_str, ampm)
    local h = tonumber(h_str)
    if not h then return nil end
    ampm = ampm:lower()
    if ampm == "am" then
        if h == 12 then h = 0 end
    else
        if h ~= 12 then h = h + 12 end
    end
    return h
end

local function _set_anchor(year, month, day1, hour, minute, reason)
    local ts = _total_seconds(year, month, day1 - 1, hour, minute)
    C.mume_start_epoch = os.time() - ts
    C.last_sync_epoch  = os.time()
    C.last_sync_reason = reason
end

local function _persist()
    local f = io.open(TMP_PATH, "w")
    if not f then return end
    f:write(string.format("mume_start_epoch=%d\n", C.mume_start_epoch))
    f:write(string.format("last_sync_epoch=%d\n",  C.last_sync_epoch or 0))
    f:write(string.format("last_sync_reason=%s\n", C.last_sync_reason or ""))
    f:write(string.format("precision=%s\n",        P_NAME[C.precision]))
    f:close()
    os.rename(TMP_PATH, CLOCK_STATE_PATH)
end

local function _read_value(key)
    local f = io.open(CLOCK_STATE_PATH, "r")
    if not f then return nil end
    for line in f:lines() do
        local k, v = line:match("^([^=]+)=(.*)$")
        if k == key then f:close(); return v end
    end
    f:close()
    return nil
end

local function _load()
    local se = tonumber(_read_value("mume_start_epoch"))
    if not se then
        C.mume_start_epoch = SEED_EPOCH
        C.precision        = P.UNSET
        return
    end
    local lse     = tonumber(_read_value("last_sync_epoch")) or 0
    local lsr     = _read_value("last_sync_reason") or ""
    local prec_s  = _read_value("precision") or "UNSET"
    local prec    = P[prec_s] or P.UNSET
    local age     = os.time() - lse
    if age > 7 * 86400 then
        C.mume_start_epoch = SEED_EPOCH
        C.precision        = P.UNSET
    elseif age > 86400 then
        C.mume_start_epoch = se
        C.last_sync_epoch  = lse
        C.last_sync_reason = lsr
        C.precision        = P.DAY
    else
        C.mume_start_epoch = se
        C.last_sync_epoch  = lse
        C.last_sync_reason = lsr
        C.precision        = prec
    end
end

-- ---------------------------------------------------------------------------
-- Sync handlers
-- ---------------------------------------------------------------------------

local function _apply_sun(body)
    if not body then return end
    local what = body.what
    if what ~= "rise" and what ~= "set" then return end
    if C.precision < P.DAY then
        dbg("[CLOCK] sun " .. what .. " skipped: precision < DAY")
        return
    end
    local m = _compute_moment()
    local h = what == "rise" and dawn[m.month + 1] or dusk[m.month + 1]
    _set_anchor(m.year, m.month, m.day, h, 0, "sun_" .. what)
    C.precision = P.MINUTE
    _persist()
    dbg("[CLOCK] sync: " .. what .. " → MINUTE")
end

local function _apply_time_line(line)
    -- Pattern 1: "8 am on Mersday, the 26th of Solmath, year 2973 of the Third Age."
    local h_s, ampm, day_s, mon_s, yr_s =
        line:match("^(%d+) (%a+) on %a+, the (%w+) of (%a+), year (%d+) of the Third Age%.$")
    if h_s then
        local day_n = _parse_day(day_s)
        local mon_n = _parse_month(mon_s)
        local yr_n  = tonumber(yr_s)
        local hr_n  = _parse_hour24(h_s, ampm)
        if day_n and mon_n and yr_n and hr_n then
            _set_anchor(yr_n, mon_n, day_n, hr_n, 0, "time_dated")
            C.precision = P.HOUR
            _persist()
            dbg("[CLOCK] sync: time_dated → HOUR")
        end
        return
    end
    -- Pattern 2: "Mersday, the 26th of Solmath, year 2973 of the Third Age."
    local day_s2, mon_s2, yr_s2 =
        line:match("^%a+, the (%w+) of (%a+), year (%d+) of the Third Age%.$")
    if day_s2 then
        local day_n = _parse_day(day_s2)
        local mon_n = _parse_month(mon_s2)
        local yr_n  = tonumber(yr_s2)
        if day_n and mon_n and yr_n then
            _set_anchor(yr_n, mon_n, day_n, 0, 0, "time_day")
            C.precision = P.DAY
            _persist()
            dbg("[CLOCK] sync: time_day → DAY")
        end
    end
end

local function _apply_room_clock(line)
    if C.precision < P.DAY then
        dbg("[CLOCK] room_clock skipped: precision < DAY")
        return
    end
    -- "The current time is 8:00am."
    local h_s, min_s, ampm = line:match("^The current time is (%d+):(%d+)(%a+)%.$")
    if not h_s then return end
    local hr_n  = _parse_hour24(h_s, ampm)
    local min_n = tonumber(min_s)
    if not hr_n or not min_n then return end
    local m = _compute_moment()
    _set_anchor(m.year, m.month, m.day, hr_n, min_n, "room_clock")
    C.precision = P.MINUTE
    _persist()
    dbg("[CLOCK] sync: room_clock → MINUTE")
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

function C.now()
    if C.precision == P.UNSET then return nil end
    return _compute_moment()
end

function C.format(style)
    style = style or "compact"
    if C.precision == P.UNSET then return "?" end
    local m  = _compute_moment()
    local mn = month_name[m.month] or "?"
    if style == "compact" then
        if C.precision == P.MINUTE then
            return string.format("%d:%02d, %s %d", m.hour, m.minute, mn, m.day)
        elseif C.precision == P.HOUR then
            local disp = m.hour % 12
            if disp == 0 then disp = 12 end
            local ampm = m.hour < 12 and "am" or "pm"
            return string.format("~%d %s, %s %d", disp, ampm, mn, m.day)
        else -- DAY
            return string.format("%s %d, %d", mn, m.day, m.year)
        end
    elseif style == "full" then
        local wd = weekday_name[m.weekday] or "?"
        return string.format("%s, the %dth of %s, year %d (%s)",
            wd, m.day, mn, m.year, m.season)
    else -- debug
        return string.format("mse=%d prec=%s %d/%02d/%02d %d:%02d",
            C.mume_start_epoch, P_NAME[C.precision],
            m.year, m.month + 1, m.day, m.hour, m.minute)
    end
end

function C.tick()
    if C.precision == P.UNSET then return end
    local m   = _compute_moment()
    local cur = m.hour * 60 + m.minute
    if C._last_emitted_minute ~= cur then
        C._last_emitted_minute = cur
    end
end

-- ---------------------------------------------------------------------------
-- Subscriptions
-- ---------------------------------------------------------------------------

events.subscribe("event_sun", function(body)
    _apply_sun(body)
end)

events.subscribe("mume_time_line", function(line)
    _apply_time_line(line)
end)

events.subscribe("room_clock_line", function(line)
    _apply_room_clock(line)
end)

-- ---------------------------------------------------------------------------
-- Startup
-- ---------------------------------------------------------------------------

_load()
dbg("[CLOCK] loaded")
