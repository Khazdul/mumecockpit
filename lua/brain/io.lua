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
    tintin_cmd("gts", "#class {core} {open}")
    tintin_cmd("gts", cmd)
    tintin_cmd("gts", "#class {core} {close}")
    if GAME_SESSION then
        tintin_cmd(GAME_SESSION, "#class {core} {open}")
        tintin_cmd(GAME_SESSION, cmd)
        tintin_cmd(GAME_SESSION, "#class {core} {close}")
    end
end

-- Register a command in GAME_SESSION only.
-- Use for: #action, #unaction — triggers only fire in the session
-- where MUD output arrives. Safe to call when GAME_SESSION is nil.
function session_cmd(cmd)
    if GAME_SESSION then
        tintin_cmd(GAME_SESSION, "#class {core} {open}")
        tintin_cmd(GAME_SESSION, cmd)
        tintin_cmd(GAME_SESSION, "#class {core} {close}")
    else
        dbg("session_cmd: no session")
    end
end
