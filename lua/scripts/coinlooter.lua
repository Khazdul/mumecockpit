-- ============================================================
--  coinlooter
-- ============================================================
-- @summary  Auto-loots coins after mob kills
-- @alias    cl    Pick up coin piles in the current room
-- @help     Subscribes to mob_death and sends the appropriate
-- @help     get-coins command on each kill:
-- @help
-- @help       Living mob killed  →  get coins all.corpse
-- @help       Undead mob killed  →  get all.coins
-- @help
-- @help     1-second debounce: at most one auto-loot per second
-- @help     so rapid kills do not double-send.
-- @help
-- @help     The `cl` alias is a manual override — bypasses the
-- @help     debounce and grabs any coin piles on the room floor.

local M = {}
scripts.coinlooter = M

local _locked = false

function M._unlock()
    _locked = false
end

function M.loot_room()
    send("get all.coins")
end

events.subscribe("mob_death", function(name, kind)
    if _locked then return end
    if kind == "living" then
        send("get coins all.corpse")
    elseif kind == "undead" then
        send("get all.coins")
    else
        return
    end
    _locked = true
    session_cmd("#delay {coinlooter_unlock} {#lua {scripts.coinlooter._unlock()}} {1}")
end)

game_cmd('#alias {cl} {#lua {scripts.coinlooter.loot_room()}}')

dbg("[COINLOOTER] loaded")
