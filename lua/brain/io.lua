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

-- Resolve a command-name token (the letters after `#`, any case) to one
-- of the four core-priority kinds, mirroring tt++'s unambiguous-prefix
-- rule. Returns the canonical kind on an unambiguous case-insensitive
-- prefix match of length ≥ 2 (e.g. `hi` → `highlight`, `sub` →
-- `substitute`). Returns nil for length-1 tokens, tokens longer than any
-- canonical name, and ambiguous prefixes. Mirrors
-- bridge/launcher/profile_io.py:resolve_kind for the same four kinds.
local _CORE_PRIORITY_KINDS = {"action", "alias", "highlight", "substitute"}

local function _resolve_priority_kind(token)
    if #token < 2 then return nil end
    local t = token:lower()
    local match
    for _, k in ipairs(_CORE_PRIORITY_KINDS) do
        if #t <= #k and k:sub(1, #t) == t then
            if match then return nil end
            match = k
        end
    end
    return match
end

-- Count balanced top-level `{...}` groups in `cmd[start..]`. Nested
-- braces inside a group don't add to the count. Returns -1 on unbalanced
-- braces (so the caller treats the input as "not exactly 2" and leaves
-- it alone).
local function _count_top_brace_groups(cmd, start)
    local count = 0
    local n = #cmd
    local i = start
    while i <= n do
        local c = cmd:sub(i, i)
        if c == "{" then
            local depth = 1
            i = i + 1
            while i <= n and depth > 0 do
                local d = cmd:sub(i, i)
                if d == "{" then depth = depth + 1
                elseif d == "}" then depth = depth - 1
                end
                i = i + 1
            end
            if depth ~= 0 then return -1 end
            count = count + 1
        elseif c == "}" then
            return -1
        else
            i = i + 1
        end
    end
    return count
end

-- Auto-inject `{3}` priority for #action / #alias / #highlight /
-- #substitute registrations that omit an explicit priority. Returns
-- `cmd` unchanged unless the command token resolves to one of those
-- four kinds AND there are exactly two top-level brace groups (pattern
-- + body, no explicit priority). Other kinds (#delay, #unaction, #var,
-- #event, …) and explicit-priority forms pass through untouched.
-- Realises the helper-side half of ADR 0115's core priority band.
local function _inject_core_priority(cmd)
    local n = #cmd
    if n < 2 or cmd:sub(1, 1) ~= "#" then return cmd end
    local j = 2
    while j <= n and cmd:sub(j, j):match("%a") do
        j = j + 1
    end
    local token = cmd:sub(2, j - 1)
    if _resolve_priority_kind(token) == nil then return cmd end
    if _count_top_brace_groups(cmd, j) == 2 then
        return cmd .. " {3}"
    end
    return cmd
end

-- Register `cmd` against `ses` inside the {core} class atomically.
-- Writes one relay file whose first line carries the open/cmd/close triple
-- as three `;`-separated, individually `#<ses>`-prefixed statements. tt++
-- runs `;`-separated statements on one input line as a unit before
-- servicing any other session's socket input, so no foreign #class
-- operation in another session can interleave between open and close and
-- steal the registration. `cmd` is filtered through `_inject_core_priority`
-- exactly once so #action/#alias/#highlight/#substitute land in the core
-- priority band (ADR 0115); the `<cmd>` substring is otherwise byte-
-- identical to what tintin_cmd would write, preserving delayed $var /
-- %capture substitution in registered bodies. See ADR 0097.
local function _tintin_class_core_cmd(ses, cmd)
    _tintin_cmd_seq = _tintin_cmd_seq + 1
    local path = string.format("bridge/ipc/cmd_%d.tin", _tintin_cmd_seq)
    local f, err = io.open(path, "w")
    if not f then
        dbg("tintin_class_core_cmd ERROR: cannot open " .. path .. " — " .. tostring(err))
        return
    end
    cmd = _inject_core_priority(cmd)
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
