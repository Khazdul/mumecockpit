-- Passive character-state collector.
-- Merges Char.Name, Char.StatusVars, Char.Vitals into state.char.*
-- using generic flat-copy (kebab-case keys converted to snake_case).
-- No alias, no register_script — background collector only.

-- TODO: prev_xp is never reset on reconnect or character switch.
-- A stale value suppresses at most one spurious delta log. Revisit
-- when session lifecycle hooks are wired up.
local prev_xp = nil

local function merge_flat(body)
    body = body or {}
    for k, v in pairs(body) do
        state.char[k:gsub("-", "_")] = v
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
    if body.xp then
        if prev_xp and body.xp > prev_xp then
            local delta = body.xp - prev_xp
            dbg(string.format(
                "[CHAR] xp gained: +%d (total %d)",
                delta, body.xp))
        end
        prev_xp = body.xp
    end
end

dbg("[CHAR_STATE] loaded")
