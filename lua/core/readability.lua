-- Readability module loader.
-- Reads startup.conf for enabled modules, loads them into the
-- {readability} tt++ class via session_cmd. Hot-reloadable via
-- scripts.readability.reload().

local M = {}
scripts.readability = M

local CONF_PATH   = "bridge/runtime/startup.conf"
local MODULE_DIR  = "ttpp/readability/modules/"

local function read_enabled_modules()
    local fh = io.open(CONF_PATH, "r")
    if not fh then return {} end
    local modules = {}
    for line in fh:lines() do
        local val = line:match("^%s*readability_enabled%s*=%s*(.-)%s*$")
        if val then
            for name in val:gmatch("[^,]+") do
                name = name:match("^%s*(.-)%s*$")
                if name ~= "" then
                    local probe = io.open(MODULE_DIR .. name .. ".tin", "r")
                    if probe then
                        probe:close()
                        modules[#modules + 1] = name
                    else
                        ui_warn("Readability module " .. ui_var(name) .. " not found, skipping.")
                    end
                end
            end
            break
        end
    end
    fh:close()
    return modules
end

local function load_modules(modules)
    if #modules == 0 then return end
    local list = table.concat(modules, ";")
    session_cmd("readability_load {" .. list .. "}")
    script_ui("READABILITY", "Loaded " .. table.concat(modules, ", ") .. ".")
end

function M.reload()
    if not GAME_SESSION then
        ui_warn("Readability reload skipped, no active session.")
        return
    end
    local modules = read_enabled_modules()
    if #modules == 0 then
        session_cmd("readability_clear")
        script_ui("READABILITY", "All modules cleared.")
    else
        local list = table.concat(modules, ";")
        session_cmd("readability_reload {" .. list .. "}")
        script_ui("READABILITY", "Reloaded " .. table.concat(modules, ", ") .. ".")
    end
end

events.subscribe("run_started", function()
    load_modules(read_enabled_modules())
end)

dbg("readability: loaded")
