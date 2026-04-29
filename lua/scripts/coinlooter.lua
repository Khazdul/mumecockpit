-- ===== COINLOOTER =====
-- Auto-loots coins after mob kills.
--   Living kill → get coins all.corpse
--   Undead kill → get coins (floor loot)
-- 1-second debounce prevents double-sends on rapid kills.

local M = {}
scripts.coinlooter = M

local _locked = false

function M._unlock()
    _locked = false
end

events.subscribe("mob_death", function(name, kind)
    if _locked then return end
    if kind == "living" then
        send("get coins all.corpse")
    elseif kind == "undead" then
        send("get coins")
    else
        return
    end
    _locked = true
    session_cmd("#delay {coinlooter_unlock} {#lua {scripts.coinlooter._unlock()}} {1}")
end)

register_script({
    alias   = "coinlooter",
    summary = "auto-loot coins after mob kills",
    help    = {
        "Subscribes to mob_death and sends the appropriate get-coins command.",
        "",
        "  Living mob killed  →  get coins all.corpse",
        "  Undead mob killed  →  get coins",
        "",
        "1-second debounce: at most one loot send per second.",
        "Always-on — toggle support via the main menu is planned.",
    }
})

dbg("[COINLOOTER] loaded")
