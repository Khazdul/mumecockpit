-- ===== LUA BRAIN — entry point =====
-- Communicates with tt++ via stdout/stdin (#run session).
-- Loads submodules under lua/brain/ and runs the main dispatch loop.

package.path = "lua/lib/?.lua;" .. package.path

local TT_SESSION = "gts"

-- Global namespace skeletons — submodules populate these.
scripts  = {}
state    = { char = {}, room = {}, comm = { history = {}, channels = {}, max_size = 1000 }, core = {}, world = {} }
gmcp     = { handlers = {} }
_scripts = {}
handlers = {}  -- handle_event() dispatch table

-- Load order matters: ui first because everything logs; io before connection
-- because game_cmd/session_cmd must exist when GAME_SESSION is first set;
-- events before gmcp because dispatch calls events.emit; registry before
-- loader because register_script must exist when scripts load.
dofile("lua/brain/ui.lua")           -- loggers + UI helpers
dofile("lua/brain/io.lua")           -- tt++ relay (uses dbg)
dofile("lua/brain/events.lua")       -- event bus (uses dbg)
dofile("lua/brain/gmcp.lua")         -- GMCP dispatch (uses events.emit, dbg)
dofile("lua/brain/connection.lua")   -- MUME state + popups (uses system_ui, dbg)
dofile("lua/brain/registry.lua")     -- register_script + cockpit help
dofile("lua/brain/loader.lua")       -- core + scripts loader

gmcp.null = require("dkjson").null

-- Central tt++ → Lua dispatch entry point (called from #run session via stdin).
function handle_event(ses, line)
    if line == "" then return end
    -- Direct Lua call: functionname(args)
    if line:match("^[%w_][%w_%.]*%(") then
        local fn, err = load(line)
        if fn then
            local ok, err2 = pcall(fn)
            if not ok then dbg("LUA ERROR: " .. tostring(err2)) end
        else
            dbg("LUA SYNTAX ERROR: " .. tostring(err))
        end
        return
    end
    -- Structured event: TYPE:arg1:arg2:...
    local parts = {}
    for p in line:gmatch("[^:]+") do parts[#parts+1] = p end
    local typ = table.remove(parts, 1)
    local handler = handlers[typ]
    if handler then handler(parts) else dbg("UNKNOWN EVENT: " .. line) end
end

-- USER_INPUT: raw SENT OUTPUT forwarded via session_cmd in stored_spells.lua.
-- Parts are rejoined with ":" because raw input may itself contain ":".
-- Guard against empty payload: IAC negotiation and similar fire SENT OUTPUT
-- with empty %0 and must not reach the event bus.
handlers["USER_INPUT"] = function(parts)
    local raw = table.concat(parts, ":")
    if raw == "" then return end
    events.emit("user_input", raw)
end

handlers["EMPTY_INPUT"] = function(_)
    events.emit("user_input_empty")
end

-- Startup
dbg("Lua brain started (" .. _VERSION .. ")")
os.execute("mkdir -p bridge/ipc data/runs data/comm data/characters data/shared")
_clear_connection_state()
local _n_core, _n_scripts = load_scripts()
dbg(_n_core .. " core + " .. _n_scripts .. " scripts loaded")

for line in io.lines() do
    handle_event(TT_SESSION, line)
end
