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
local _C_TEXT   = "\027[1;97m"             -- bold bright white — base message text
local _C_VAR    = "\027[1;38;2;255;238;88m" -- bold yellow #FFEE58 — dynamic values in ui messages
local _C_SYSTEM = "\027[38;2;66;165;245m"  -- blue #42A5F5 — system events
local _C_WARN   = "\027[38;2;255;179;0m"   -- amber      #FFB300 — warnings
local _C_ERR    = "\027[38;2;229;57;53m"   -- red        #E53935 — errors
local _C_RESET  = "\027[0m"

function script_ui(name, msg)
    ui(string.format("%s▶ %s:%s %s%s%s", _C_SCRIPT, name, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_var(v) — wraps a dynamic value (session name, target, reason,
-- filename, etc.) in the variable-highlight style (bold yellow).
--
-- Appends _C_TEXT after the trailing reset so text following the
-- variable continues in the base message colour (bold bright white)
-- rather than falling back to the terminal default. This makes
-- ui_var safe to use mid-message without colour bleed.
function ui_var(v)
    return _C_VAR .. tostring(v) .. _C_RESET .. _C_TEXT
end

-- system_ui(msg) — infrastructure lifecycle events (brain start,
-- game session connect/disconnect, cockpit reload, etc.).
-- Format: ● SYSTEM: message.
function system_ui(msg)
    ui(string.format("%s● SYSTEM:%s %s%s%s", _C_SYSTEM, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_warn(msg) — surface a warning to the UI pane (amber).
-- Use only when the player should see the warning — routine/recoverable
-- issues with no player impact go to dbg() instead.
-- Format: ⚠ WARN: message.
function ui_warn(msg)
    ui(string.format("%s⚠ WARN:%s %s%s%s", _C_WARN, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_err(msg) — surface an error to the UI pane (red).
-- Use only when the player should see the error.
-- Format: ✖ ERROR: message.
function ui_err(msg)
    ui(string.format("%s✖ ERROR:%s %s%s%s", _C_ERR, _C_RESET, _C_TEXT, msg, _C_RESET))
end

local SESSION_STATE_PATH = "bridge/session.state"

-- Plain line-by-line parse — never sources/executes the file.
local function _read_startup_conf_value(key)
    local f = io.open("bridge/startup.conf", "r")
    if not f then return nil end
    for line in f:lines() do
        local k, v = line:match("^([^=]+)=(.*)$")
        if k == key then f:close(); return v end
    end
    f:close()
    return nil
end

local function _write_session_state()
    local mode = _read_startup_conf_value("connection_mode") or "mmapper"
    local tmp  = SESSION_STATE_PATH .. ".tmp"
    local f    = io.open(tmp, "w")
    if not f then return end
    f:write(string.format("connected_at=%d\nconnection_mode=%s\n",
                          os.time(), mode))
    f:close()
    os.rename(tmp, SESSION_STATE_PATH)
end

local function _clear_session_state()
    os.remove(SESSION_STATE_PATH)
end

local function _popup_is_open()
    local f = io.open("bridge/.popup_open", "r")
    if f then f:close(); return true end
    return false
end

local function _open_popup()
    os.execute('tmux display-popup -E -w 80% -h 80% -x C -y C "bash $HOME/MUME/bridge/ingame_menu.sh" >/dev/null 2>&1 &')
end

GAME_SESSION = nil  -- set dynamically when a game session connects

-- mark_mume_connected() / mark_mume_disconnected() — idempotent, transition-only.
-- Drive bridge/session.state from GMCP (Char.Name → connected, Core.Goodbye → disconnected).
-- Only act (and only emit system_ui) on the actual state change; detect via file existence.
function mark_mume_connected()
    local f = io.open(SESSION_STATE_PATH, "r")
    if f then f:close(); return end
    _write_session_state()
    system_ui("Connected to MUME.")
    if state.session and state.session.reset then state.session.reset() end
end

function mark_mume_disconnected()
    local f = io.open(SESSION_STATE_PATH, "r")
    if not f then return end
    f:close()
    _clear_session_state()
    system_ui("Disconnected from MUME.")
    if not _popup_is_open() then _open_popup() end
    if state.session and state.session.reset then state.session.reset() end
    if state.char and state.char.reset then state.char.reset() end
end

function set_game_session(ses)
    GAME_SESSION = ses
    system_ui("tt++ session " .. ui_var(ses) .. " open.")
    tintin_cmd("gts", "#var {game_session} {" .. ses .. "}")
end

-- Called when a game session disconnects. Clears GAME_SESSION
-- only if it matches the disconnecting session — guards against
-- stale clears if somehow called with wrong session name.
-- Delegates to mark_mume_disconnected() so the direct-mode abrupt-drop
-- path joins the single dispatch point (popup auto-open, dedup guard).
function clear_game_session(ses)
    if GAME_SESSION == ses then
        GAME_SESSION = nil
        mark_mume_disconnected()
        system_ui("tt++ session " .. ui_var(ses) .. " closed.")
        tintin("gts", "#unvar game_session")
    else
        dbg("clear_game_session: mismatch")
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
        dbg("session_cmd: no session")
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
end

-- Called after all scripts load. Builds cockpit / cockpit -help dynamically
-- so the Scripts section reflects whatever scripts are actually installed.
local function _register_cockpit_help()
    local body = {
        "  Connection:",
        "   connect    connect to MUME",
        "",
        "  Window management:",
        "   cp -i       toggle input pane",
        "   cp -u       toggle UI pane",
        "   cp -m       toggle comm pane",
        "   cp -c       toggle status pane",
        "   cp -d       toggle dev pane",
        "   cp -h       toggle headers",
        "   cp -s       save profile to disk",
        "   cp -r       full system reload",
        "   cp -e       full system shutdown",
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

-- Writes _scripts registry to bridge/scripts.cache for the startup menu.
-- Called after all scripts have called register_script() and
-- _register_cockpit_help() has run. Overwrites on every startup.
local function _write_scripts_cache()
    local fh, err = io.open("bridge/scripts.cache", "w")
    if not fh then
        dbg("scripts.cache: failed to open — " .. tostring(err))
        return
    end
    local aliases = {}
    for a in pairs(_scripts) do aliases[#aliases + 1] = a end
    table.sort(aliases)
    for _, a in ipairs(aliases) do
        local m = _scripts[a]
        fh:write("SCRIPT:" .. a .. "\n")
        if m.summary then fh:write("SUMMARY:" .. m.summary .. "\n") end
        for _, h in ipairs(m.help or {}) do
            fh:write("HELP:" .. h .. "\n")
        end
    end
    fh:close()
end

-- Namespaces available to all scripts (set before dofile):
--   scripts                   — namespace for script public APIs
--   state.char/.room/.comm    — namespace for shared game state
--   gmcp                      — GMCP subsystem (handlers, dispatch, modules)
scripts = {}
state   = {
    char  = {},
    room  = {},
    comm  = {
        history  = {},
        channels = {},
        filters  = {},
        max_size = 500,
    },
    core  = {},
    world = {},
}
gmcp    = {
    handlers = {},
    -- Keep in sync with Core.Supports.Set payload in ttpp/core/gmcp.tin.
    modules  = { "Char 1", "Comm.Channel 1", "Event 1", "Core 1" },
    trace    = true,
}
events  = {
    handlers = {},
    trace    = true,
}

function events.subscribe(name, fn)
    if not events.handlers[name] then
        events.handlers[name] = {}
    end
    local t = events.handlers[name]
    t[#t+1] = fn
    return fn
end

function events.unsubscribe(name, fn)
    local t = events.handlers[name]
    if not t then return end
    for i = #t, 1, -1 do
        if t[i] == fn then
            table.remove(t, i)
        end
    end
end

function events.emit(name, ...)
    local t = events.handlers[name]
    if events.trace then
        local args = {...}
        local strs = {}
        for _, v in ipairs(args) do strs[#strs+1] = tostring(v) end
        dbg(string.format("[EVENTS] %s = %s", name, table.concat(strs, ", ")))
    end
    if not t then return end
    for _, fn in ipairs(t) do
        local ok, err = pcall(fn, ...)
        if not ok then
            dbg("events handler error [" .. name .. "]: " .. tostring(err))
        end
    end
end

function gmcp.dispatch(module, payload)
    payload = payload or ""
    local json = require("dkjson")

    -- %2 from IAC SB GMCP includes the package name as a prefix,
    -- e.g. "Char.Name {...}" or just "Core.Goodbye" with no body.
    -- Strip everything up to and including the first whitespace;
    -- remainder is the JSON body (or empty for no-body messages).
    local json_body = payload:match("^%S+%s+(.*)$") or ""
    json_body = json_body:match("^%s*(.-)%s*$")   -- trim

    local body = nil
    if json_body ~= "" then
        local parsed, _, err = json.decode(json_body, 1, json.null)
        if err then
            dbg("GMCP parse error [" .. module .. "]: "
                .. err .. " | body=" .. json_body)
            return
        end
        body = parsed
    end

    if gmcp.trace then
        local encoded = body and json.encode(body) or "(nil)"
        dbg(string.format("[GMCP] %s = %s", module, encoded))
    end

    local handler = gmcp.handlers[module]
    if handler then
        local ok, err2 = pcall(handler, body)
        if not ok then
            dbg("GMCP handler error [" .. module .. "]: "
                .. tostring(err2))
        end
    else
        dbg("GMCP no handler: " .. module)
    end
end

-- -----------------------------
-- MODULES — two-tier auto-load
-- lua/core/    — always-on collectors (no alias, no register_script)
-- lua/scripts/ — opt-in automation modules (must call register_script)
-- Core is loaded first so state.* is populated before scripts run.
-- -----------------------------
local function load_scripts()
    local n_core, n_scripts = 0, 0
    local function load_dir(glob)
        local count = 0
        local p = io.popen("ls " .. glob .. " 2>/dev/null")
        if p then
            for f in p:lines() do
                dofile(f)
                count = count + 1
            end
            p:close()
        end
        return count
    end
    n_core    = load_dir("lua/core/*.lua")
    n_scripts = load_dir("lua/scripts/*.lua")
    _register_cockpit_help()
    _write_scripts_cache()
    return n_core, n_scripts
end

-- -----------------------------
-- STARTUP
-- -----------------------------
package.path = "lua/lib/?.lua;" .. package.path
gmcp.null = require("dkjson").null
dbg("Lua brain started (" .. _VERSION .. ")")
_clear_session_state()
local _n_core, _n_scripts = load_scripts()
dbg(_n_core .. " core + " .. _n_scripts .. " scripts loaded")

-- Main loop
for line in io.lines() do
    handle_event(TT_SESSION, line)
end
