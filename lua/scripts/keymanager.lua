-- ============================================================
--  keymanager
-- ============================================================
-- @summary  Port-key library: capture locate-life results, store and list keys
-- @alias    kpick   Store key [n] from the last locate as <name> (no args: re-show list)
-- @alias    keys    List your stored port keys
-- @help     Cast locate-life normally — e.g. `cast 'locate life' troll`.
-- @help     The raw result rows are gagged and reshown as a numbered,
-- @help     reformatted pick list with a hint box. Then:
-- @help
-- @help       kpick <n> <name>  store pick #n's key under <name> (12 h expiry)
-- @help       kpick             re-show the last pick list
-- @help       keys              list your stored keys with time remaining
-- @help
-- @help     Keys are per-character and survive reconnect; they expire 12 h
-- @help     after being picked. This pass captures and stores keys only —
-- @help     it does not feed them to teleport/portal yet.

-- Self-contained Pattern-2 script (docs/scripts.md, docs/ipc.md). tt++ does the
-- latency-light reflex — recognise & gag locate rows, fire the blank-line
-- terminator — and Lua owns all state (the pick buffer + the key library) and
-- all rendering. There is NO sent-output snoop and NO `locatel` alias: locate
-- output is self-identifying, so we arm on the first matching row, not on input.
--
-- Private state lives in file-local tables (no other consumer reads it), not in
-- state.*. The key library is persisted per character, mirroring lua/core/
-- charm.lua's persistence shape: atomic temp+os.rename write, reload on
-- gmcp_char_name with expired-entry pruning, dkjson.

local json = require("dkjson")

local EXPIRY = 12 * 3600   -- a picked key lives 12 hours

-- tt++ 24-bit truecolor palette (mirror lua/scripts/mercenaries.lua)
local FRAME = "<F9AA8B7>"
local TITLE = "<FD4A04E>"
local WHITE = "<FFFFFFF>"
local DIM   = "<F555555>"
local R     = "<099>"

-- ---------------------------------------------------------------------------
-- File-local state
-- ---------------------------------------------------------------------------

local M = {}
scripts.keymanager = M

-- pick      current locate's reformatted rows: { name, room_type, distance, key }
-- in_block  true while a locate block is accumulating rows; the first row after
--           a render starts a fresh block (resets pick)
-- library   name → { key, room_type, stored_at, expires_at } — persisted
local pick     = {}
local in_block = false
local library  = {}

-- ---------------------------------------------------------------------------
-- Parse — Lua translation of the agreed regex. Same pattern matches self-locate
-- rows (e.g. "Sumba - Indoors  Very near  key: '...'") — no special case.
--   g1 = mob name, g2 = room-type (verbatim), g3 = distance, g4 = key
-- ---------------------------------------------------------------------------

local ROW_PAT = "^(.-)%s+%-%s+(.-)%s%s+(.-)%s%s+key:%s+'(.+)'$"

-- ---------------------------------------------------------------------------
-- Persistence (mirror lua/core/charm.lua) — per-character key library
-- ---------------------------------------------------------------------------

local function _char_dir(name)
    return os.getenv("HOME") .. "/MUME/data/characters/" .. name .. "/"
end

-- Atomic temp-file + os.rename write of `library`. An empty library is written
-- as {} (not deleted), so reconnect always finds a definitive file. dkjson
-- encodes an empty Lua table as [], so the empty case is special-cased.
local function _save_library()
    local cname = state.char.name
    if not cname then return end
    local dir = _char_dir(cname)
    os.execute("mkdir -p '" .. dir .. "'")
    local path = dir .. "portkeys.json"
    local tmp  = path .. ".tmp"
    local encoded
    if next(library) == nil then
        encoded = "{}"
    else
        local ok, enc = pcall(json.encode, library)
        if not ok then
            dbg("[KEYMANAGER] encode failed: " .. tostring(enc))
            return
        end
        encoded = enc
    end
    local f = io.open(tmp, "w")
    if not f then
        dbg("[KEYMANAGER] open tmp failed: " .. tmp)
        return
    end
    f:write(encoded)
    f:close()
    os.rename(tmp, path)
end

-- Reload the persisted library on login, dropping any whose 12 h elapsed during
-- downtime (lazy expiry — no timer). Always resets `library` to a clean slate
-- first so a character with no file starts empty.
local function _load_library(cname)
    library = {}
    local path = _char_dir(cname) .. "portkeys.json"
    local f = io.open(path, "r")
    if not f then
        dbg("[KEYMANAGER] restored 0 (0 expired)")
        return
    end
    local content = f:read("*a")
    f:close()
    local ok, loaded = pcall(json.decode, content)
    if not ok or type(loaded) ~= "table" then
        dbg("[KEYMANAGER] load failed for " .. cname)
        return
    end
    local now      = os.time()
    local restored = 0
    local expired  = 0
    for name, e in pairs(loaded) do
        if e.expires_at and e.expires_at <= now then
            expired = expired + 1
        else
            library[name] = e
            restored = restored + 1
        end
    end
    dbg("[KEYMANAGER] restored " .. restored .. " (" .. expired .. " expired)")
end

-- Lazy prune: drop expired entries, persisting only if anything changed.
local function _prune_library()
    local now     = os.time()
    local changed = false
    for name, e in pairs(library) do
        if e.expires_at and e.expires_at <= now then
            library[name] = nil
            changed = true
        end
    end
    if changed then _save_library() end
end

-- Return the stored name of a non-expired library entry whose key matches, or
-- nil. Duplicate pick rows sharing a key therefore both mark.
local function _lib_name_for_key(key)
    local now = os.time()
    for name, e in pairs(library) do
        if e.key == key and e.expires_at and e.expires_at > now then
            return name
        end
    end
    return nil
end

-- ---------------------------------------------------------------------------
-- Rendering helpers (all via tintin_show into the game session)
-- ---------------------------------------------------------------------------

-- Visual cell width: count UTF-8 code points (skip continuation bytes
-- 0x80–0xBF). Every glyph used here — box-drawing, arrow, em-dash, ASCII — is
-- one cell. Unlike mercenaries' _vlen this does NOT strip `<...>`: we never
-- embed tt++ colour codes inside a measured string (colours are concatenated
-- outside), and the one place a literal `<...>` appears in display text — the
-- hint box's `<n> <name>` — must be counted as the visible characters it is, so
-- the box border lines up.
local function _vlen(s)
    if not s or s == "" then return 0 end
    local n = 0
    for i = 1, #s do
        local b = s:byte(i)
        if b < 0x80 or b >= 0xC0 then n = n + 1 end
    end
    return n
end

local function _ses()
    return GAME_SESSION or "gts"
end

local function _status(msg)
    tintin_show(_ses(), FRAME .. "## KEYS: " .. WHITE .. msg .. R)
end

-- Pick list — brackets, key visible, room-type verbatim, left-aligned columns
-- whose widths are computed from the buffer. A row whose key matches a
-- non-expired library entry is dimmed and suffixed " → <name>". A hint box of
-- matching width follows.
local function _render_picks()
    local ses = _ses()
    if #pick == 0 then
        _status("no locate results captured yet.")
        return
    end

    local idx_w, name_w, room_w, dist_w, key_w = 0, 0, 0, 0, 0
    for i, e in ipairs(pick) do
        idx_w  = math.max(idx_w,  #("[" .. i .. "]"))
        name_w = math.max(name_w, _vlen(e.name))
        room_w = math.max(room_w, _vlen(e.room_type))
        dist_w = math.max(dist_w, _vlen(e.distance))
        key_w  = math.max(key_w,  _vlen(e.key))
    end

    local GAP   = 2   -- spaces between columns
    local max_w = 0
    local rows  = {}
    for i, e in ipairs(pick) do
        local idx    = "[" .. i .. "]"
        local stored = _lib_name_for_key(e.key)
        local color  = stored and DIM or WHITE

        local body = idx       .. string.rep(" ", idx_w  - #idx + GAP)
            .. e.name          .. string.rep(" ", name_w - _vlen(e.name) + GAP)
            .. e.room_type     .. string.rep(" ", room_w - _vlen(e.room_type) + GAP)
            .. e.distance      .. string.rep(" ", dist_w - _vlen(e.distance) + GAP)
            .. e.key
        if stored then
            body = body .. string.rep(" ", key_w - _vlen(e.key)) .. " → " .. stored
        end

        rows[#rows + 1] = color .. body .. R
        max_w = math.max(max_w, _vlen(body))
    end

    for _, row in ipairs(rows) do
        tintin_show(ses, row)
    end

    -- Hint box under the list, width matching the widest row.
    local label = "┌─ kpick <n> <name> to store "
    local pad   = max_w - _vlen(label) - 1   -- -1 for the trailing ┐
    if pad < 0 then pad = 0 end
    tintin_show(ses, FRAME .. label .. string.rep("─", pad) .. "┐" .. R)
end

-- Remaining-time label: hours if ≥ 1 h, else minutes.
local function _format_expires(secs)
    if secs < 0 then secs = 0 end
    if secs >= 3600 then
        return math.floor(secs / 3600) .. " h"
    end
    return math.floor(secs / 60) .. " m"
end

-- ---------------------------------------------------------------------------
-- Public API — called from tt++ #action / #alias bodies via #lua
-- ---------------------------------------------------------------------------

-- Row handler: receives the ENTIRE raw locate line as one opaque payload (it
-- contains both single quotes and a colon, so it is never colon-split — see
-- docs/ipc.md). The first row after a render opens a new block and resets the
-- pick buffer; every parsed row is appended.
function M.row(raw)
    local name, room_type, distance, key = raw:match(ROW_PAT)
    if not key then
        dbg("[KEYMANAGER] row parse miss: " .. tostring(raw))
        return
    end
    if not in_block then
        pick     = {}
        in_block = true
    end
    pick[#pick + 1] = {
        name      = name,
        room_type = room_type,
        distance  = distance,
        key       = key,
    }
end

-- Terminator handler: the locate block has ended. Clear in_block (so the next
-- locate starts fresh) but KEEP the buffer (kpick reads it afterwards), then
-- render.
function M.render()
    in_block = false
    _render_picks()
end

-- kpick <n> <name>: store pick #n's key under <name> with a 12 h expiry.
-- kpick (no args): re-render the current pick list (stored markers show).
function M.kpick(n, name)
    if n == nil or n == "" then
        _render_picks()
        return
    end
    local idx = tonumber(n)
    if not idx or idx < 1 or idx > #pick then
        _status("no pick #" .. tostring(n) .. " in the last locate.")
        return
    end
    if name == nil or name == "" then
        _status("usage: kpick <n> <name>.")
        return
    end

    local e        = pick[idx]
    local existing = library[name]
    local now      = os.time()
    library[name] = {
        key        = e.key,
        room_type  = e.room_type,
        stored_at  = now,
        expires_at = now + EXPIRY,
    }
    _save_library()

    if existing then
        _status("Replaced " .. name .. ": " .. existing.key .. " → " .. e.key .. ".")
    else
        _status("Stored " .. e.key .. " as " .. name .. " (expires in 12 h).")
    end
end

-- keys: list the library (expired entries pruned first), sorted by name.
function M.keys()
    _prune_library()
    local ses = _ses()
    if next(library) == nil then
        _status("Your key library is empty.")
        return
    end

    local names = {}
    for name in pairs(library) do names[#names + 1] = name end
    table.sort(names)

    -- Column widths from headers and data.
    local h_name, h_room, h_key, h_exp = "Name", "Room-type", "Key", "Expires"
    local name_w = _vlen(h_name)
    local room_w = _vlen(h_room)
    local key_w  = _vlen(h_key)
    local exp_w  = _vlen(h_exp)
    local now    = os.time()
    local exp_of = {}
    for _, name in ipairs(names) do
        local e = library[name]
        exp_of[name] = _format_expires(e.expires_at - now)
        name_w = math.max(name_w, _vlen(name))
        room_w = math.max(room_w, _vlen(e.room_type))
        key_w  = math.max(key_w,  _vlen(e.key))
        exp_w  = math.max(exp_w,  _vlen(exp_of[name]))
    end

    local GAP   = 2
    local total = name_w + room_w + key_w + exp_w + 3 * GAP

    local function _cols(c1, c2, c3, c4)
        return c1 .. string.rep(" ", name_w - _vlen(c1) + GAP)
            .. c2  .. string.rep(" ", room_w - _vlen(c2) + GAP)
            .. c3  .. string.rep(" ", key_w  - _vlen(c3) + GAP)
            .. c4
    end

    -- Centred title over the table width.
    local title    = "Key library"
    local left_pad = math.floor((total - _vlen(title)) / 2)
    if left_pad < 0 then left_pad = 0 end
    tintin_show(ses, string.rep(" ", left_pad) .. TITLE .. title .. R)
    tintin_show(ses, DIM .. _cols(h_name, h_room, h_key, h_exp) .. R)
    for _, name in ipairs(names) do
        local e = library[name]
        tintin_show(ses, WHITE .. _cols(name, e.room_type, e.key, exp_of[name]) .. R)
    end
end

-- ---------------------------------------------------------------------------
-- tt++ trigger registration (session-scoped → {core}, re-armed per run)
-- ---------------------------------------------------------------------------

-- The row trigger and the standalone "very confused" gag are registered via
-- session_cmd, so they land in {core} and never serialise into the saved
-- profile (ADR 0049/0097). Re-registered on each run_started, mirroring
-- lua/scripts/mercenaries.lua.
--
-- Row trigger: matches any result row ending in `key: '<key>'` (loose — the
-- precise parse is in Lua). On match it gags the raw line, forwards the ENTIRE
-- raw line (%0) to M.row as one opaque payload, and installs the blank-line
-- terminator. The terminator install is a fire-time registration, so it is
-- wrapped in its OWN {core}-open/close pair as one ;-joined statement run
-- (ADR 0097) — session_cmd's wrap covers the row action's registration, not
-- what the row action does when it later fires. Re-installing the terminator
-- per row is idempotent (a named #action replaces). The terminator gags the
-- blank line, renders the buffer, then removes itself.
local function _register_triggers()
    session_cmd([[#unaction {  key: '%1'$}]])
    session_cmd([[#action {  key: '%1'$} {#line gag;#lua {scripts.keymanager.row("%0")};#class {core} {open};#action {^$} {#line gag;#lua {scripts.keymanager.render()};#unaction {^$}};#class {core} {close}}]])

    -- Interrupted-concentration line. Unconditional per design: locate is the
    -- common context. NB if this exact string proves to fire for other
    -- interrupted spells too, scope it to in-block instead (gate the gag on
    -- `in_block`); for now it is gagged whenever it appears.
    session_cmd([[#unaction {^You feel very confused and can't concentrate any more.$}]])
    session_cmd([[#action {^You feel very confused and can't concentrate any more.$} {#line gag}]])
end

events.subscribe("run_started", _register_triggers)

-- ---------------------------------------------------------------------------
-- Per-character (re)load — cold start and reconnect
-- ---------------------------------------------------------------------------

events.subscribe("gmcp_char_name", function()
    if state.char.name then
        _load_library(state.char.name)
    else
        library = {}
    end
end)

-- ---------------------------------------------------------------------------
-- Aliases (registered at load, survive reconnect via game_cmd → {core})
-- ---------------------------------------------------------------------------

game_cmd([[#alias {kpick} {#lua {scripts.keymanager.kpick("%1", "%2")}}]])
game_cmd([[#alias {keys}  {#lua {scripts.keymanager.keys()}}]])

dbg("[KEYMANAGER] loaded")
