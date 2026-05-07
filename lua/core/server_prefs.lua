-- Re-asserts server-side preferences on every Char.Name update.
--
-- Subscribes to gmcp_char_name (emitted by dispatch after char_state.lua's
-- primary writer runs). Issues two width commands:
--
--   change width all 500   — locks server-side line wrap to a width MUME
--                            never reaches in a single logical line, preventing
--                            trigger patterns from being split across lines.
--   change width table terminal — sets terminal-width reporting to follow the actual
--                            terminal so MUME formats screen-aware output correctly.
--
-- Both sends are idempotent and handle reconnects and server restarts transparently.

events.subscribe("gmcp_char_name", function()
    send("change width all 500")
    send("change width table terminal")
end)

dbg("[SERVER_PREFS] loaded")
