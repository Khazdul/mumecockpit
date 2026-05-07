-- lua/brain/registry.lua
-- Exports: register_script, _write_scripts_cache, _register_cockpit_help, _build_box
-- Depends on: tintin_cmd (io.lua), dbg (ui.lua), _scripts (brain.lua skeleton)

local _BOX_W = 50  -- inner width: chars between ║ borders

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
function _build_box(title, body_lines)
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
function _register_cockpit_help()
    local body = {
        "  Connection:",
        "   connect    connect to MUME",
        "",
        "  Window management:",
        "   cp -u       toggle UI pane",
        "   cp -m       toggle comm pane",
        "   cp -c       toggle status pane",
        "   cp -b       toggle buffs pane",
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

-- Writes _scripts registry to bridge/runtime/scripts.cache for the startup menu.
-- Called after all scripts have called register_script() and
-- _register_cockpit_help() has run. Overwrites on every startup.
function _write_scripts_cache()
    local fh, err = io.open("bridge/runtime/scripts.cache", "w")
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
