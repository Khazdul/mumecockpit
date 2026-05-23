-- lua/brain/io.lua
-- Exports: tintin, tintin_cmd, tintin_show, send, game_cmd, session_cmd
-- Depends on: dbg (ui.lua), GAME_SESSION (set at runtime by connection.lua)

-- -----------------------------
-- TT++ COMMUNICATION
-- tintin(ses, cmd)     — relay-based: run a simple TT++ command with no braces
--                        e.g. tintin("mume", "look")
-- tintin_cmd(ses, cmd) — file-based: run a TT++ command that contains braces
--                        e.g. tintin_cmd("mume", "#action {pat} {body}")
--                        Writes "#ses cmd" to a unique file, signals TT++ via
--                        tintin_read. TT++ reads the file in lua session context;
--                        the "#ses" prefix dispatches to the target session.
--                        Each call gets a unique file — no race conditions.
--                        TT++ deletes the file after reading.
-- tintin_show(ses, msg) — #showme msg in session 'ses'
--                         use GAME_SESSION to display in the MUD window
-- send(cmd)            — send a MUD command to GAME_SESSION
-- -----------------------------

local _tintin_cmd_seq = 0

function tintin(ses, cmd)
    print(string.format("tintin (%s) %s", ses, cmd))
    io.flush()
end

function tintin_cmd(ses, cmd)
    _tintin_cmd_seq = _tintin_cmd_seq + 1
    local path = string.format("bridge/ipc/cmd_%d.tin", _tintin_cmd_seq)
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

-- Register `cmd` against `ses` inside the {core} class atomically.
-- Writes one relay file whose first line carries the open/cmd/close triple
-- as three `;`-separated, individually `#<ses>`-prefixed statements. tt++
-- runs `;`-separated statements on one input line as a unit before
-- servicing any other session's socket input, so no foreign #class
-- operation in another session can interleave between open and close and
-- steal the registration. The `<cmd>` substring is byte-identical to what
-- tintin_cmd would write, preserving delayed $var / %capture substitution
-- in registered bodies. See ADR 0097.
local function _tintin_class_core_cmd(ses, cmd)
    _tintin_cmd_seq = _tintin_cmd_seq + 1
    local path = string.format("bridge/ipc/cmd_%d.tin", _tintin_cmd_seq)
    local f, err = io.open(path, "w")
    if not f then
        dbg("tintin_class_core_cmd ERROR: cannot open " .. path .. " — " .. tostring(err))
        return
    end
    f:write(string.format(
        "#%s #class {core} {open};#%s %s;#%s #class {core} {close}\n",
        ses, ses, cmd, ses))
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

-- Register a command in both gts and GAME_SESSION.
-- Use for: #alias, #substitute, #highlight
-- Safe to call before a game session exists (GAME_SESSION nil = skip game session).
function game_cmd(cmd)
    _tintin_class_core_cmd("gts", cmd)
    if GAME_SESSION then
        _tintin_class_core_cmd(GAME_SESSION, cmd)
    end
end

-- Register a command in GAME_SESSION only.
-- Use for: #action, #unaction — triggers only fire in the session
-- where MUD output arrives. Safe to call when GAME_SESSION is nil.
function session_cmd(cmd)
    if GAME_SESSION then
        _tintin_class_core_cmd(GAME_SESSION, cmd)
    else
        dbg("session_cmd: no session")
    end
end
