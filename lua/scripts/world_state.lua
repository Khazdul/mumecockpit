-- Passive world-state collector.
-- Stores Event.Darkness and Event.Sun bodies into state.world.
-- Body shape is undocumented — gmcp.trace will reveal the real shape
-- from live traffic.
-- No alias, no register_script — background collector only.

gmcp.handlers["Event.Darkness"] = function(body)
    state.world.darkness = body
end

gmcp.handlers["Event.Sun"] = function(body)
    state.world.sun = body
end

dbg("[WORLD_STATE] loaded")
