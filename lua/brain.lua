-- ===== LUA BRAIN =====
-- Communicates with tt++ via stdout/stdin (#run session)
-- UI output to logs/ui.log (persistent), debug to logs/debug.log

local UI_LOG    = "logs/ui.log"
local DEBUG_LOG = "logs/debug.log"

local TT_SESSION = "gts"

-- -----------------------------
-- LOGGERS
-- -----------------------------
local debug_fh  = io.open(DEBUG_LOG, "a")
local ui_log_fh = io.open(UI_LOG, "a")

function dbg(msg)
    if debug_fh then
        debug_fh:write(os.date("[%H:%M:%S] ") .. msg .. "\n")
        debug_fh:flush()
    end
end

function ui(msg)
    if ui_log_fh then
        ui_log_fh:write(msg .. "\n")
        ui_log_fh:flush()
    end
    dbg("UI: " .. msg)
end

-- script_ui(name, msg) — structured status line for the UI pane.
-- Format:  ▪ NAME - message
-- Use for key state changes only: started, stopped, errors.
-- Not for per-cycle noise or debug detail.
local _C_SCRIPT = "\027[38;2;38;198;218m"  -- teal  #26C6DA
local _C_TEXT   = "\027[97m"               -- bright white
local _C_RESET  = "\027[0m"

function script_ui(name, msg)
    ui(string.format("%s▪ %s%s - %s%s%s", _C_SCRIPT, name, _C_RESET, _C_TEXT, msg, _C_RESET))
end

GAME_SESSION = nil  -- set dynamically when a game session connects

function set_game_session(ses)
    GAME_SESSION = ses
    dbg("GAME_SESSION set to: " .. ses)
    ui("Game session: " .. ses)
    tintin_cmd("gts", "#var {game_session} {" .. ses .. "}")
end

-- Called when a game session disconnects. Clears GAME_SESSION
-- only if it matches the disconnecting session — guards against
-- stale clears if somehow called with wrong session name.
function clear_game_session(ses)
    if GAME_SESSION == ses then
        GAME_SESSION = nil
        dbg("GAME_SESSION cleared (was: " .. ses .. ")")
        ui("Game session: none")
        tintin("gts", "#unvar game_session")
    else
        dbg("clear_game_session: ignored " .. ses ..
            " (current: " .. tostring(GAME_SESSION) .. ")")
    end
end

-- Register a command in both gts and GAME_SESSION.
-- Use for: #alias, #substitute, #highlight
-- Safe to call before a game session exists (GAME_SESSION nil = skip game session).
function game_cmd(cmd)
    tintin_cmd("gts", cmd)
    if GAME_SESSION then
        tintin_cmd(GAME_SESSION, cmd)
    end
end

-- Register a command in GAME_SESSION only.
-- Use for: #action, #unaction — triggers only fire in the session
-- where MUD output arrives. Safe to call when GAME_SESSION is nil.
function session_cmd(cmd)
    if GAME_SESSION then
        tintin_cmd(GAME_SESSION, cmd)
    else
        dbg("session_cmd ignored (no game session): " .. cmd)
    end
end

-- -----------------------------
-- TT++ COMMUNICATION
-- tintin(ses, cmd)   — relay-based: run a simple TT++ command with no braces
--                      e.g. tintin("mume", "look")
-- tintin_cmd(ses, cmd) — file-based: run a TT++ command that contains braces
--                        e.g. tintin_cmd("mume", "#action {pat} {body}")
--                        Writes "#ses cmd" to a unique file, signals TT++ via
--                        tintin_read. TT++ reads the file in lua session context;
--                        the "#ses" prefix dispatches to the target session.
--                        Each call gets a unique file — no race conditions.
--                        TT++ deletes the file after reading.
-- tintin_show(ses, msg) — #showme msg in session 'ses'
--                         use GAME_SESSION to display in the MUD window
-- send(cmd)          — send a MUD command to GAME_SESSION
-- -----------------------------
local _tintin_cmd_seq = 0

function tintin(ses, cmd)
    print(string.format("tintin (%s) %s", ses, cmd))
    io.flush()
end

function tintin_cmd(ses, cmd)
    _tintin_cmd_seq = _tintin_cmd_seq + 1
    local path = string.format("logs/cmd_%d.tin", _tintin_cmd_seq)
    local f, err = io.open(path, "w")
    if not f then
        dbg("tintin_cmd ERROR: cannot open " .. path .. " — " .. tostring(err))
        return
    end
    -- The file contains "#ses cmd" so TT++ dispatches to the right session when read.
    f:write(string.format("#%s %s\n", ses, cmd))
    f:write(string.format("#system {rm -f %s}\n", path))
    f:close()
    print("tintin_read " .. path)
    io.flush()
end

function tintin_show(ses, msg)
    print(string.format("tintin_show (%s) %s", ses, msg))
    io.flush()
end

function send(cmd)
    if not GAME_SESSION then
        dbg("SEND ignored (no game session): " .. cmd)
        return
    end
    dbg("SEND: " .. cmd)
    tintin(GAME_SESSION, cmd)
end

-- -----------------------------
-- SCRIPT REGISTRY
-- Scripts call register_script(meta) at load time; _register_cockpit_help()
-- builds _cockpit_help after all scripts load.
-- -----------------------------
local _scripts = {}
local _BOX_W   = 50  -- inner width: chars between ║ borders

local function _pad(s, width)
    if #s > width then s = s:sub(1, width) end
    return s .. string.rep(" ", width - #s)
end

-- Returns one #showme command for a box content row.
-- content is padded to (_BOX_W - 2) with 1-space border on each side.
local function _box_row(content)
    return "#showme {║ " .. _pad(content, _BOX_W - 2) .. " ║}"
end

-- Builds a list of #showme commands that render a bordered box.
-- Returns the list; join with ";" to embed in an alias body.
local function _build_box(title, body_lines)
    local hr    = string.rep("═", _BOX_W)
    local blank = "║" .. string.rep(" ", _BOX_W) .. "║"
    local parts = {}
    parts[#parts+1] = "#showme { }"
    parts[#parts+1] = "#showme {╔" .. hr .. "╗}"
    parts[#parts+1] = _box_row(title)
    parts[#parts+1] = "#showme {╠" .. hr .. "╣}"
    for _, l in ipairs(body_lines) do
        if l == "" then
            parts[#parts+1] = "#showme {" .. blank .. "}"
        else
            -- Strip {} to avoid unbalanced braces inside the alias body
            parts[#parts+1] = _box_row(l:gsub("[{}]", ""))
        end
    end
    parts[#parts+1] = "#showme {╚" .. hr .. "╝}"
    parts[#parts+1] = "#showme { }"
    return parts
end

-- register_script(meta) — called by scripts at load time.
-- meta = { alias="name", summary="short desc (<=22 chars)", help={"line", ...} }
-- Registers cockpit -<alias> showing a detailed help box.
function register_script(meta)
    _scripts[meta.alias] = meta
    local body = {}
    if meta.summary then
        body[#body+1] = "  " .. meta.summary
        body[#body+1] = ""
    end
    for _, l in ipairs(meta.help or {}) do
        body[#body+1] = "  " .. l
    end
    local parts = _build_box("  " .. meta.alias:upper(), body)
    tintin_cmd("gts", "#alias {cp -" .. meta.alias .. "} {" .. table.concat(parts, ";") .. "}")
    dbg("register_script: " .. meta.alias)
end

-- Called after all scripts load. Builds cockpit / cockpit -help dynamically
-- so the Scripts section reflects whatever scripts are actually installed.
local function _register_cockpit_help()
    local body = {
        "  Connection:",
        "   mume              connect via MMapper",
        "",
        "  Window management:",
        "   cp -u       toggle UI pane",
        "   cp -d       toggle dev pane",
        "   cp -h       toggle headers",
        "   cp -s       show system status",
        "   cp -r       full system reload",
        "   cp -e       kill session",
        "",
    }
    if next(_scripts) then
        body[#body+1] = "  Scripts  (type cp -<name> for details):"
        local aliases = {}
        for a in pairs(_scripts) do aliases[#aliases+1] = a end
        table.sort(aliases)
        for _, a in ipairs(aliases) do
            local m = _scripts[a]
            body[#body+1] = string.format("   %-18s %s", "cp -" .. a, m.summary or "")
        end
        body[#body+1] = ""
    end
    local parts = _build_box("  COCKPIT SYSTEM", body)
    local body_str = table.concat(parts, ";")
    -- _cockpit_help is a private name; aliases.tin's {cp} calls it at priority 6
    tintin_cmd("gts", "#alias {_cockpit_help} {" .. body_str .. "}")
    dbg("_register_cockpit_help: done")
end

-- -----------------------------
-- EVENT HANDLERS
-- Centralized dispatch for structured MUD server events (TYPE:arg1:arg2:...).
-- Scripts register their own handlers at load time:
--   handlers["TELL"] = function(parts) ... end
-- -----------------------------
local handlers = {}

-- -----------------------------
-- EXPOSED FUNCTIONS (called via #lua from tt++)
-- -----------------------------
function handle_event(ses, line)
    dbg("EVENT IN: " .. line)

    -- Direct Lua call: functionname(args)
    if line:match("^[%w_]+%(") then
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
    for p in line:gmatch("[^:]+") do
        parts[#parts+1] = p
    end
    local typ = table.remove(parts, 1)
    local handler = handlers[typ]
    if handler then
        handler(parts)
    else
        dbg("UNKNOWN EVENT: " .. line)
    end
end

-- -----------------------------
-- MODULES — auto-loaded from lua/scripts/
-- Each script is self-contained: registers its own aliases/triggers at load time.
-- -----------------------------
local function load_scripts()
    local p = io.popen("ls lua/scripts/*.lua 2>/dev/null")
    if p then
        for f in p:lines() do
            dofile(f)
        end
        p:close()
    end
    _register_cockpit_help()
end
load_scripts()

-- -----------------------------
-- STARTUP
-- -----------------------------
ui("=== LUA BRAIN STARTED ===")
dbg(string.format("session=%s, lua=%s", TT_SESSION, _VERSION))
tintin_show("gts", "Lua brain ready.")

-- Main loop
for line in io.lines() do
    handle_event(TT_SESSION, line)
end
