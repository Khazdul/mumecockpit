-- Passive character-state collector.
-- Merges Char.Name, Char.StatusVars, Char.Vitals into state.char.*
-- using generic flat-copy (kebab-case keys converted to snake_case).
-- No alias, no register_script — background collector only.

local function merge_flat(body)
    body = body or {}
    for k, v in pairs(body) do
        local key = k:gsub("-", "_")
        if v == gmcp.null then
            state.char[key] = nil
        else
            state.char[key] = v
        end
    end
end

gmcp.handlers["Char.Name"] = function(body)
    merge_flat(body)
    mark_mume_connected()
end
gmcp.handlers["Char.StatusVars"] = merge_flat

gmcp.handlers["Char.Vitals"] = function(body)
    body = body or {}
    merge_flat(body)
end

function state.char.reset()
    for k, v in pairs(state.char) do
        if type(v) ~= "function" then
            state.char[k] = nil
        end
    end
    events.emit("char_reset")
end

dbg("[CHAR_STATE] loaded")
