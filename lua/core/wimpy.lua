-- Passive wimpy collector.
-- Subscribes to wimpy_changed from mud_events.tin and updates state.char.wimpy.
-- No alias, no metadata header — background collector only.

events.subscribe("wimpy_changed", function(raw)
    local s = (raw or ""):gsub("%.$", "")
    local n = tonumber(s)
    if not n then
        dbg("[WIMPY] parse fail: " .. tostring(raw))
        return
    end
    state.char.wimpy = n
end)

dbg("[WIMPY] loaded")
