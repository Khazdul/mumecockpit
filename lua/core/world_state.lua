-- Passive world-state collector.
-- Stores Event.Darkness, Event.Moon, Event.Moved, and Event.Sun bodies into state.world.
-- No alias, no metadata header — background collector only.

gmcp.handlers["Event.Darkness"] = function(body)
    state.world.darkness = body
end

gmcp.handlers["Event.Sun"] = function(body)
    state.world.sun = body
end

gmcp.handlers["Event.Moon"] = function(body)
    state.world.moon = body
end

gmcp.handlers["Event.Moved"] = function(body)
    state.world.moved = body
end

dbg("[WORLD_STATE] loaded")
