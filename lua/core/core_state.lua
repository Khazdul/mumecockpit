-- Passive GMCP collector for Core.* messages.
-- No alias, no metadata header — background collector only.

gmcp.handlers["Core.Goodbye"] = function(body)
    dbg(string.format("[CORE] goodbye: %s", tostring(body)))
    mark_mume_disconnected()
end

gmcp.handlers["Core.Ping"] = function(body)
    -- server-initiated only; we don't send Core.Ping
    state.core.last_ping = os.time()
end

dbg("[CORE_STATE] loaded")
