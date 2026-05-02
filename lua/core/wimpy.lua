-- Passive wimpy collector.
-- Subscribes to wimpy_changed from mud_events.tin, updates state.char.wimpy,
-- and emits script_ui. No alias, no register_script — background collector only.

events.subscribe("wimpy_changed", function(raw)
    local s = (raw or ""):gsub("%.$", "")
    local n = tonumber(s)
    if not n then
        dbg("[WIMPY] parse fail: " .. tostring(raw))
        return
    end    
    
    state.char.wimpy = n
--    if n == 0 then
--        script_ui("WIMPY", "Removed.")
--    else
--        script_ui("WIMPY", "Set to " .. ui_var(n) .. ".")
--    end
end)

dbg("[WIMPY] loaded")
