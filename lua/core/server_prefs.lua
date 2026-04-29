-- Re-asserts server-side preferences on every Char.Name update.
--
-- Wraps char_state's Char.Name handler (load order is alphabetical, so
-- char_state is in place by the time this file loads). The original handler
-- runs first; then we issue two width commands:
--
--   change width all 500   — locks server-side line wrap to a width MUME
--                            never reaches in a single logical line, preventing
--                            trigger patterns from being split across lines.
--   change width terminal  — sets terminal-width reporting to follow the actual
--                            terminal so MUME formats screen-aware output correctly.
--
-- Both sends are idempotent and handle reconnects and server restarts transparently.

local _orig_name = gmcp.handlers["Char.Name"]

gmcp.handlers["Char.Name"] = function(body)
    if _orig_name then _orig_name(body) end
    send("change width all 500")
    send("change width table terminal")
end

dbg("[SERVER_PREFS] loaded")
