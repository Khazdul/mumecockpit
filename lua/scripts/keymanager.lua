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

-- tt++ 24-bit truecolor palette (mirror lua/scripts/mercenaries.lua). `<Fxxxxxx>`
-- sets the foreground only (bg untouched); the full reset `<099>` clears both —
-- which is what lets the zebra bands below switch fg per column without losing
-- the row background (see _zebra_row).
local FRAME = "<F9AA8B7>"
local TITLE = "<FD4A04E>"
local WHITE = "<FFFFFFF>"
local DIM   = "<F555555>"
local R     = "<099>"

-- Column palette — same column, same colour in BOTH views (locate + keys).
local NAME   = "<F7FC8C0>"   -- soft cyan  — name, most important, never white
local DIST   = "<F9FB0D0>"   -- soft blue  — distance / normal expiry
local ROOM   = "<F8C8C82>"   -- muted      — room-type
local KEY    = "<F6F6F6F>"   -- grey       — key, least important
local HEADER = "<F888888>"   -- dim        — header labels and bottom hint
local STORED = "<F8FBF8F>"   -- green      — stored marker (→ name)
local ORANGE = "<FD4A04E>"   -- orange     — expiry under 1 h
local Z_A    = "<B161616>"   -- zebra band A (odd data rows)
local Z_B    = "<B212121>"   -- zebra band B (even data rows)

-- Box geometry: one space of breathing room inside each border, GAP between
-- columns. The widest row therefore never touches a border.
local LEAD  = 1
local TRAIL = 1
local GAP   = 2

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

-- Visual cell width (mirror mercenaries' _vlen): strip tt++ markup (`<...>`, all
-- zero-width) then count UTF-8 code points by skipping continuation bytes
-- (0x80–0xBF). Every glyph used here — box-drawing, arrow, em-dash, ASCII — is
-- one cell. We now build coloured cells and measure them in place, so the strip
-- is required. The one display string with a literal `<...>` that must survive
-- measurement — the hint label's `<n> <name>` — is measured by _rawlen instead.
local function _vlen(s)
    if not s or s == "" then return 0 end
    local stripped = s:gsub("<[^>]*>", "")
    local n = 0
    for i = 1, #stripped do
        local b = stripped:byte(i)
        if b < 0x80 or b >= 0xC0 then n = n + 1 end
    end
    return n
end

-- Raw cell width: like _vlen but WITHOUT the markup strip — for the hint label,
-- whose literal `<n> <name>` are visible characters, not colour codes.
local function _rawlen(s)
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

-- ── box primitives (dynamic width — mirror mercenaries' border helpers) ──────

-- Frame a content run in `│ … │` with frame-coloured borders. The content is
-- responsible for its own reset before the closing border.
local function _wrap_row(content)
    return FRAME .. "│" .. R .. content .. FRAME .. "│" .. R
end

-- Top border with a centred, title-coloured caption. `title` carries its own
-- surrounding spaces; `inner_w` is the box inner width.
local function _top_border(inner_w, title)
    local dashes = inner_w - _vlen(title)
    if dashes < 0 then dashes = 0 end
    local left  = math.floor(dashes / 2)
    local right = dashes - left
    return FRAME .. "╭" .. string.rep("─", left) .. R
        .. TITLE .. title .. R
        .. FRAME .. string.rep("─", right) .. "╮" .. R
end

local function _bottom_border(inner_w)
    return FRAME .. "╰" .. string.rep("─", inner_w) .. "╯" .. R
end

-- Bottom border carrying a left-aligned hint label, then dashes to the corner.
local function _bottom_hint(inner_w, label)
    local pre, post = "─ ", " "
    local fill = inner_w - _rawlen(pre) - _rawlen(label) - _rawlen(post)
    if fill < 0 then fill = 0 end
    return FRAME .. "╰" .. pre .. R .. HEADER .. label .. R
        .. FRAME .. post .. string.rep("─", fill) .. "╯" .. R
end

-- Header row: a plain (non-zebra) content run, LEAD-indented, padded to width.
local function _header_row(inner_w, core)
    local pad = inner_w - LEAD - _vlen(core)
    if pad < 0 then pad = 0 end
    return _wrap_row(string.rep(" ", LEAD) .. core .. string.rep(" ", pad) .. R)
end

-- Zebra data row: set the band background ONCE, switch fg per column inside the
-- core, pad with bg-carrying spaces to the inner width, then a single full reset
-- right before the closing border (so the border itself is never striped).
local function _zebra_row(inner_w, bg, core)
    local pad = inner_w - LEAD - _vlen(core)
    if pad < 0 then pad = 0 end
    return _wrap_row(bg .. string.rep(" ", LEAD) .. core .. string.rep(" ", pad) .. R)
end

-- Pick list — a bordered, zebra-striped panel. Columns, in order:
--   [idx]  Name  Distance  Room-type  Key   (→ <name> if already stored)
-- A row whose key matches a non-expired library entry shows a WHITE index and a
-- green "→ <name>" after the key (the only stored markers; the rest of the row
-- is not dimmed). The bottom border carries the kpick hint. Width is the widest
-- of every row (incl. the stored marker), the header, the title and the hint.
local function _render_picks()
    local ses = _ses()
    if #pick == 0 then
        _status("no locate results captured yet.")
        return
    end

    -- Column widths from header labels and data.
    local idx_w  = _vlen("#")
    local name_w = _vlen("Name")
    local dist_w = _vlen("Dist")
    local room_w = _vlen("Room-type")
    local key_w  = _vlen("Key")
    for i, e in ipairs(pick) do
        idx_w  = math.max(idx_w,  _vlen("[" .. i .. "]"))
        name_w = math.max(name_w, _vlen(e.name))
        dist_w = math.max(dist_w, _vlen(e.distance))
        room_w = math.max(room_w, _vlen(e.room_type))
        key_w  = math.max(key_w,  _vlen(e.key))
    end

    -- Coloured cores (the column run, no bg, no outer padding).
    local cores = {}
    for i, e in ipairs(pick) do
        local idx    = "[" .. i .. "]"
        local stored = _lib_name_for_key(e.key)
        local idx_c  = stored and WHITE or DIM
        local parts  = {
            idx_c .. idx        .. string.rep(" ", idx_w  - _vlen(idx)         + GAP),
            NAME  .. e.name     .. string.rep(" ", name_w - _vlen(e.name)      + GAP),
            DIST  .. e.distance .. string.rep(" ", dist_w - _vlen(e.distance)  + GAP),
            ROOM  .. e.room_type.. string.rep(" ", room_w - _vlen(e.room_type) + GAP),
            KEY   .. e.key,
        }
        if stored then
            parts[#parts + 1] = string.rep(" ", key_w - _vlen(e.key) + GAP)
                .. STORED .. "→ " .. stored
        end
        cores[i] = table.concat(parts)
    end

    -- Header core (dim), aligned to the same columns; no label over the marker.
    local hdr = HEADER
        .. "#"         .. string.rep(" ", idx_w  - _vlen("#")         + GAP)
        .. "Name"      .. string.rep(" ", name_w - _vlen("Name")      + GAP)
        .. "Dist"      .. string.rep(" ", dist_w - _vlen("Dist")      + GAP)
        .. "Room-type" .. string.rep(" ", room_w - _vlen("Room-type") + GAP)
        .. "Key"

    local title = "  LOCATE (" .. #pick .. ")  "
    local hint  = "kpick <n> <name> to store"

    local content_w = _vlen(hdr)
    for _, c in ipairs(cores) do content_w = math.max(content_w, _vlen(c)) end
    local inner_w = math.max(
        LEAD + content_w + TRAIL,
        _vlen(title),
        _rawlen("─ ") + _rawlen(hint) + _rawlen(" "))

    tintin_show(ses, " ")   -- leading blank line so the box never glues to the prompt
    tintin_show(ses, _top_border(inner_w, title))
    tintin_show(ses, _header_row(inner_w, hdr))
    for i, c in ipairs(cores) do
        tintin_show(ses, _zebra_row(inner_w, (i % 2 == 1) and Z_A or Z_B, c))
    end
    tintin_show(ses, _bottom_hint(inner_w, hint))
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

    -- Column widths from header labels and data.
    local name_w = _vlen("Name")
    local room_w = _vlen("Room-type")
    local key_w  = _vlen("Key")
    local exp_w  = _vlen("Expires")
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

    -- Header core (dim) and data cores, aligned to the same columns. Expires
    -- turns orange when under 1 h remaining, otherwise soft blue.
    local hdr = HEADER
        .. "Name"      .. string.rep(" ", name_w - _vlen("Name")      + GAP)
        .. "Room-type" .. string.rep(" ", room_w - _vlen("Room-type") + GAP)
        .. "Key"       .. string.rep(" ", key_w  - _vlen("Key")       + GAP)
        .. "Expires"

    local cores = {}
    for _, name in ipairs(names) do
        local e     = library[name]
        local exp   = exp_of[name]
        local exp_c = (e.expires_at - now < 3600) and ORANGE or DIST
        cores[#cores + 1] = NAME .. name           .. string.rep(" ", name_w - _vlen(name)         + GAP)
            .. ROOM .. e.room_type .. string.rep(" ", room_w - _vlen(e.room_type) + GAP)
            .. KEY  .. e.key       .. string.rep(" ", key_w  - _vlen(e.key)       + GAP)
            .. exp_c .. exp
    end

    local title = "  KEY LIBRARY  "
    local content_w = _vlen(hdr)
    for _, c in ipairs(cores) do content_w = math.max(content_w, _vlen(c)) end
    local inner_w = math.max(LEAD + content_w + TRAIL, _vlen(title))

    tintin_show(ses, " ")   -- leading blank line so the box never glues to the prompt
    tintin_show(ses, _top_border(inner_w, title))
    tintin_show(ses, _header_row(inner_w, hdr))
    for i, c in ipairs(cores) do
        tintin_show(ses, _zebra_row(inner_w, (i % 2 == 1) and Z_A or Z_B, c))
    end
    tintin_show(ses, _bottom_border(inner_w))
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
    session_cmd([[#unaction {^%1  key: '%2'$}]])
    session_cmd([[#action {^%1  key: '%2'$} {#line gag;#lua {scripts.keymanager.row("%0")};#class {core} {open};#action {^$} {#line gag;#lua {scripts.keymanager.render()};#unaction {^$}};#class {core} {close}}]])


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
