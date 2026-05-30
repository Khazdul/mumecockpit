-- lua/brain/gmcp.lua
-- Populates: gmcp.modules, gmcp.trace, gmcp.module_to_event, gmcp.dispatch
-- Depends on: events.emit (events.lua), dbg (ui.lua), dkjson

-- Keep in sync with Core.Supports.Set payload in ttpp/core/gmcp.tin.
gmcp.modules     = { "Char 1", "Comm.Channel 1", "Event 1", "Core 1", "Group 1" }
gmcp.trace       = false
gmcp.trace_only  = { Group = false }  -- whitelist table: exact key or package prefix; nil = off

local function should_trace(module)
    if gmcp.trace then return true end
    if not gmcp.trace_only then return false end
    if gmcp.trace_only[module] then return true end
    local pkg = module:match("^([^%.]+)")
    return pkg ~= nil and gmcp.trace_only[pkg] == true
end

function gmcp.module_to_event(module)
    return "gmcp_" .. module
        :gsub("([a-z])([A-Z])", "%1_%2")
        :gsub("%.", "_")
        :lower()
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

    if should_trace(module) then
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
    end

    events.emit(gmcp.module_to_event(module), body)
end
