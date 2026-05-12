-- Cumulative XP/TP thresholds (level 1–100) and stateless progress helpers.
-- Loaded before status_state.lua (alphabetical order in lua/core/).

level_progress = {}

-- stylua: ignore
local TABLE_XP = {
         1,      1000,      3000,      7000,     15000,     30000,     60000,    105000,    165000,    240000,  -- 1-10
    330000,    435000,    555000,    690000,    840000,   1040000,   1290000,   1590000,   1940000,   2340000,  -- 11-20
   2790000,   3290000,   3840000,   4440000,   5090000,   5790000,   6540000,   7340000,   8190000,   9090000,  -- 21-30
  10040000,  11040000,  12090000,  13190000,  14290000,  15390000,  16640000,  17890000,  19145000,  20400000,  -- 31-40
  21700000,  23050000,  24400000,  25750000,  27150000,  28550000,  30000000,  31500000,  33000000,  34550000,  -- 41-50
  36150000,  37750000,  39400000,  41100000,  42850000,  44600000,  46400000,  48250000,  50000000,  52000000,  -- 51-60
  54000000,  56000000,  58000000,  60000000,  62000000,  64000000,  66500000,  68500000,  71000000,  73000000,  -- 61-70
  75500000,  77500000,  80000000,  82500000,  85000000,  87500000,  90000000,  92500000,  95000000,  97500000,  -- 71-80
 100500000, 103000000, 106000000, 108500000, 111500000, 114000000, 117000000, 120000000, 123000000, 126000000,  -- 81-90
 129000000, 132000000, 135000000, 138000000, 141500000, 144500000, 148000000, 151000000, 154500000, 158000000,  -- 91-100
}

-- stylua: ignore
local TABLE_TP = {
       0,     100,     300,     600,    1000,    1500,    2100,    2800,    3600,    4500,  -- 1-10
    5500,    6600,    7900,    9400,   11100,   13000,   15100,   17400,   19900,   22600,  -- 11-20
   25500,   28600,   32000,   35400,   38700,   42000,   45400,   48700,   52000,   55300,  -- 21-30
   58700,   62000,   65300,   68700,   72000,   75300,   78700,   82000,   85300,   88700,  -- 31-40
   92000,   95300,   98700,  102000,  105300,  108700,  112000,  115300,  118700,  122000,  -- 41-50
  125300,  128700,  132000,  135300,  138700,  142000,  145300,  148700,  152000,  155300,  -- 51-60
  158700,  162000,  165300,  168700,  172000,  175300,  178700,  182000,  185300,  188700,  -- 61-70
  192000,  195300,  198600,  202000,  205300,  208600,  212000,  215300,  218600,  222000,  -- 71-80
  225300,  228600,  232000,  235300,  238600,  242000,  245300,  248600,  252000,  255300,  -- 81-90
  258600,  262000,  265300,  268600,  272000,  275300,  278600,  282000,  285300,  288600,  -- 91-100
}

local function _progress(table, level, value, mult)
    if level == nil or value == nil then return nil end
    if level < 1 then return nil end
    if level >= 100 then return 1.0 end
    local base = table[level]     * mult
    local next = table[level + 1] * mult
    return math.max(0.0, math.min(1.0, (value - base) / (next - base)))
end

function level_progress.level_from_xp(xp)
    if xp == nil or xp <= TABLE_XP[1] then return 1 end
    if xp >= TABLE_XP[100] then return 100 end
    local L = 1
    while L < 100 and xp >= TABLE_XP[L + 1] do
        L = L + 1
    end
    return L
end

function level_progress.compute_xp_progress(xp)
    if xp == nil then return nil end
    return _progress(TABLE_XP, level_progress.level_from_xp(xp), xp, 1.0)
end

function level_progress.compute_tp_progress(xp, tp, race)
    if xp == nil or tp == nil then return nil end
    local mult = (type(race) == "string" and race:lower() == "troll") and 0.1 or 1.0
    return _progress(TABLE_TP, level_progress.level_from_xp(xp), tp, mult)
end

local function _baseline(table, level, value, run_value, mult)
    if level == nil or value == nil then return nil end
    if run_value == nil or run_value <= 0 then
        return _progress(table, level, value, mult)
    end
    if level < 1 then return nil end
    if level >= 100 then return 1.0 end
    local session_start = value - run_value
    local lvl_start = table[level]     * mult
    local lvl_end   = table[level + 1] * mult
    if lvl_end <= lvl_start then return nil end
    if session_start <= lvl_start then
        return 0   -- level-up during session: re-anchor at new level
    end
    local baseline = (session_start - lvl_start) / (lvl_end - lvl_start)
    local current  = _progress(table, level, value, mult) or 0
    if baseline < 0       then baseline = 0       end
    if baseline > current then baseline = current end
    return baseline
end

function level_progress.compute_xp_baseline(xp, run_xp)
    return _baseline(TABLE_XP, level_progress.level_from_xp(xp), xp, run_xp, 1.0)
end

function level_progress.compute_tp_baseline(xp, tp, run_tp, race)
    local mult = (type(race) == "string" and race:lower() == "troll") and 0.1 or 1.0
    return _baseline(TABLE_TP, level_progress.level_from_xp(xp), tp, run_tp, mult)
end

dbg("[LEVEL_PROGRESS] loaded")
