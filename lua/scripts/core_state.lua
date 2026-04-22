-- Passive GMCP collector for Core.* messages.
-- No alias, no register_script — background collector only.

gmcp.handlers["Core.Goodbye"] = function(body)
    -- body is a string ("Goodbye!") or nil
    dbg(string.format("[CORE] goodbye: %s", tostring(body)))
end

gmcp.handlers["Core.Ping"] = function(body)
    -- server-initiated only; we don't send Core.Ping
    state.core.last_ping = os.time()
end

dbg("[CORE_STATE] loaded")
