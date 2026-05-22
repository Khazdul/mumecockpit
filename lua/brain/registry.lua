-- lua/brain/registry.lua
-- Exports: _build_box, _register_script_help, _register_cockpit_help, _write_scripts_cache
-- Depends on: tintin_cmd (io.lua), dbg (ui.lua)
--
-- Catalog records (built by lua/brain/loader.lua) have the shape:
--   { name=<stem>, path=<file>, enabled=<bool>,
--     summary=<string|nil>, aliases={{name=,desc=},...}, help={...} }

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

-- Registers `cp -<name>` for a single enabled script, rendered from its
-- parsed metadata. Called by the loader once per enabled script.
function _register_script_help(s)
    local body = {}
    if s.summary and s.summary ~= "" then
        body[#body+1] = "  " .. s.summary
        body[#body+1] = ""
    end
    if s.aliases and #s.aliases > 0 then
        body[#body+1] = "  Aliases:"
        for _, a in ipairs(s.aliases) do
            if a.desc and a.desc ~= "" then
                body[#body+1] = string.format("    %-10s %s", a.name, a.desc)
            else
                body[#body+1] = "    " .. a.name
            end
        end
        body[#body+1] = ""
    end
    for _, l in ipairs(s.help or {}) do
        body[#body+1] = "  " .. l
    end
    local parts = _build_box("  " .. s.name:upper(), body)
    tintin_cmd("gts", "#alias {cp -" .. s.name .. "} {" .. table.concat(parts, ";") .. "}")
end

-- Called after all scripts load. Builds `cp` / `cp -help` from the catalog
-- so the Scripts section reflects whatever scripts are actually enabled.
-- Disabled scripts are not listed here — they are surfaced in the launcher's
-- Scripts view (via scripts.cache) instead.
function _register_cockpit_help(catalog)
    local body = {
        "  Connection:",
        "   connect    connect to MUME",
        "",
        "  Window management:",
        "   cp -u       toggle UI pane",
        "   cp -m       toggle comm pane",
        "   cp -c       toggle status pane",
        "   cp -b       toggle buffs pane",
        "   cp -g       toggle group pane",
        "   cp -d       toggle dev pane",
        "   cp -h       toggle headers",
        "   cp -s       save profile to disk",
        "   cp -e       full system shutdown",
        "",
    }
    local enabled = {}
    for _, s in ipairs(catalog) do
        if s.enabled then enabled[#enabled+1] = s end
    end
    if #enabled > 0 then
        body[#body+1] = "  Scripts  (type cp -<name> for details):"
        for _, s in ipairs(enabled) do
            body[#body+1] = string.format("   %-18s %s", "cp -" .. s.name, s.summary or "")
        end
        body[#body+1] = ""
    end
    local parts = _build_box("  COCKPIT SYSTEM", body)
    local body_str = table.concat(parts, ";")
    -- _cockpit_help is a private name; aliases.tin's {cp} calls it at priority 6
    tintin_cmd("gts", "#alias {_cockpit_help} {" .. body_str .. "}")
end

-- Writes the full catalog (enabled + disabled) to bridge/runtime/scripts.cache
-- for the launcher and in-game popup to render. Overwrites on every startup.
function _write_scripts_cache(catalog)
    local fh, err = io.open("bridge/runtime/scripts.cache", "w")
    if not fh then
        dbg("scripts.cache: failed to open — " .. tostring(err))
        return
    end
    for _, s in ipairs(catalog) do
        fh:write("SCRIPT:" .. s.name .. "\n")
        fh:write("ENABLED:" .. (s.enabled and "1" or "0") .. "\n")
        if s.summary and s.summary ~= "" then
            fh:write("SUMMARY:" .. s.summary .. "\n")
        end
        for _, a in ipairs(s.aliases or {}) do
            fh:write("ALIAS:" .. a.name .. "|" .. (a.desc or "") .. "\n")
        end
        for _, h in ipairs(s.help or {}) do
            fh:write("HELP:" .. h .. "\n")
        end
    end
    fh:close()
end
