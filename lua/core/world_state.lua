-- Passive world-state collector.
-- Stores Event.Darkness, Event.Moon, Event.Moved, and Event.Sun bodies into state.world.
-- Re-emits Event.Achieved as the `achievement` event and announces it in the UI
-- pane and mume main window.
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

gmcp.handlers["Event.Achieved"] = function(body)
    body = body or {}
    local what = body.what
    if what == nil or what == gmcp.null then return end
    events.emit("achievement", what)
end

events.subscribe("achievement", function(what)
    script_ui("ACHIEVEMENT", "Unlocked.")
    tintin_show(GAME_SESSION or "gts",
        "<F9AA8B7>## ACHIEVEMENT: <FFFFFFF>" .. what .. "<099>")
end)

dbg("[WORLD_STATE] loaded")
