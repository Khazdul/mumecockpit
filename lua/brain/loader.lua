-- lua/brain/loader.lua
-- Exports: load_scripts
-- Depends on: dbg (ui.lua), _register_script_help, _register_cockpit_help,
--             _write_scripts_cache (registry.lua)
--
-- Two-tier loader:
--   1. lua/core/*.lua — always-on; every file is dofile()'d unconditionally.
--   2. lua/scripts/*.lua — opt-in; each file's metadata header is parsed
--      statically (no execution), enabled state is resolved against
--      scripts.conf, and only enabled files are dofile()'d.
--
-- After loading, the full script catalog (enabled + disabled) is written to
-- bridge/runtime/scripts.cache so the launcher and in-game popup can render
-- every available script — including disabled ones, which the user toggles
-- on from the launcher's Scripts view.

-- ---------------------------------------------------------------------------
-- Header parser
-- ---------------------------------------------------------------------------
-- A script declares metadata in a comment block at the top of its file —
-- the contiguous run of `--` comment lines before the first non-comment
-- line. Inside that block, `-- @key value` lines are metadata; other
-- comment lines (decorative rules, prose) are ignored. Unknown @keys are
-- silently skipped so the parser stays forward-compatible.
--
-- Returns { summary=<string|nil>, aliases={{name=,desc=},...}, help={...} }.
local function _parse_script_header(path)
    local fh = io.open(path, "r")
    if not fh then
        return { summary = nil, aliases = {}, help = {} }
    end
    local meta = { summary = nil, aliases = {}, help = {} }
    for line in fh:lines() do
        local comment = line:match("^%s*%-%-(.*)$")
        if not comment then break end
        local key, val = comment:match("^%s*@(%w+)%s*(.*)$")
        if key then
            val = val:gsub("%s+$", "")
            if key == "summary" then
                meta.summary = val
            elseif key == "alias" then
                local aname, adesc = val:match("^(%S+)%s*(.*)$")
                if aname then
                    meta.aliases[#meta.aliases+1] = { name = aname, desc = adesc or "" }
                end
            elseif key == "help" then
                meta.help[#meta.help+1] = val
            end
            -- unknown @key: silently ignored (forward-compat)
        end
    end
    fh:close()
    return meta
end

-- ---------------------------------------------------------------------------
-- scripts.conf resolution
-- ---------------------------------------------------------------------------
-- Effective state lookup:
--   1. bridge/runtime/scripts.conf (written by the launcher) if present,
--   2. else bridge/launcher/templates/scripts.conf (shipped),
--   3. a script absent from both files → enabled.
-- Format: flat key=value, value is 1 (enabled) or 0 (disabled). `#`
-- comments and blank lines are ignored.
local function _read_scripts_conf(path)
    local fh = io.open(path, "r")
    if not fh then return nil end
    local conf = {}
    for line in fh:lines() do
        local k, v = line:match("^%s*([%w_%-]+)%s*=%s*([01])")
        if k then conf[k] = (v == "1") end
    end
    fh:close()
    return conf
end

local function _resolve_scripts_conf()
    return _read_scripts_conf("bridge/runtime/scripts.conf")
        or _read_scripts_conf("bridge/launcher/templates/scripts.conf")
        or {}
end

-- ---------------------------------------------------------------------------
-- Directory listing
-- ---------------------------------------------------------------------------
local function _list_dir(glob)
    local files = {}
    local p = io.popen("ls " .. glob .. " 2>/dev/null")
    if p then
        for f in p:lines() do files[#files+1] = f end
        p:close()
    end
    return files
end

-- ---------------------------------------------------------------------------
-- Catalog builder
-- ---------------------------------------------------------------------------
-- Walks lua/scripts/, parses each header, joins with the resolved
-- scripts.conf state, and returns an alphabetically-sorted catalog.
local function _build_script_catalog()
    local conf = _resolve_scripts_conf()
    local catalog = {}
    for _, path in ipairs(_list_dir("lua/scripts/*.lua")) do
        local name = path:match("([^/]+)%.lua$")
        local meta = _parse_script_header(path)
        local enabled = conf[name]
        if enabled == nil then enabled = true end
        catalog[#catalog+1] = {
            name    = name,
            path    = path,
            enabled = enabled,
            summary = meta.summary,
            aliases = meta.aliases,
            help    = meta.help,
        }
    end
    table.sort(catalog, function(a, b) return a.name < b.name end)
    return catalog
end

-- ---------------------------------------------------------------------------
-- Public entry — called by brain.lua at startup
-- ---------------------------------------------------------------------------
-- Returns (n_core, n_scripts) for the startup banner. n_scripts is the
-- count of enabled scripts that were actually loaded — not the catalog size.
function load_scripts()
    local n_core = 0
    for _, path in ipairs(_list_dir("lua/core/*.lua")) do
        dofile(path)
        n_core = n_core + 1
    end

    local catalog = _build_script_catalog()
    local n_scripts = 0
    for _, s in ipairs(catalog) do
        if s.enabled then
            dofile(s.path)
            _register_script_help(s)
            n_scripts = n_scripts + 1
        end
    end

    _register_cockpit_help(catalog)
    _write_scripts_cache(catalog)
    return n_core, n_scripts
end
