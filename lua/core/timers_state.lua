-- Serialises state.char.affects, state.char.stored_spells, state.char.blinds,
-- state.char.charms, and state.char.herblores to bridge/runtime/timers.state
-- (JSON) whenever affects_changed, stored_spells_changed, blinds_changed,
-- charms_changed, herblores_changed, char_reset, or gmcp_char_name fires.
--
-- Atomic write: timers.state.tmp → os.rename → timers.state.

local json       = require("dkjson")
local STATE_PATH = os.getenv("HOME") .. "/MUME/bridge/runtime/timers.state"
local TMP_PATH   = STATE_PATH .. ".tmp"

local function serialize()
    local affects = state.char.affects or {}
    local affects_out = {}
    for _, e in ipairs(affects) do
        affects_out[#affects_out + 1] = {
            name              = e.name,
            type              = e.type or json.null,
            expires_at        = e.expires_at or json.null,
            expected_duration = e.expected_duration or json.null,
            -- false only for reconciliation-added timed-capable entries
            -- that have no observed init/refresh yet; every other entry
            -- (normal timed, indefinite, reconciled-indefinite) is tracked.
            tracked           = (e.tracked ~= false),
        }
    end

    local stored_spells = state.char.stored_spells or {}
    local stored_out = {}
    for _, e in ipairs(stored_spells) do
        stored_out[#stored_out + 1] = {
            name              = e.name,
            expires_at        = e.tracked and e.expires_at or json.null,
            expected_duration = e.tracked and e.expected_duration or json.null,
            tracked           = e.tracked,
        }
    end

    local blinds = state.char.blinds or {}
    local blinds_out = {}
    for _, e in ipairs(blinds) do
        blinds_out[#blinds_out + 1] = {
            name              = e.name,
            expires_at        = e.expires_at or json.null,
            expected_duration = e.expected_duration or json.null,
        }
    end

    local charms = state.char.charms or {}
    local charms_out = {}
    for _, e in ipairs(charms) do
        charms_out[#charms_out + 1] = {
            id                = e.id,
            name              = e.name,
            started_at        = e.started_at,
            expires_at        = e.expires_at or json.null,
            expected_duration = e.expected_duration or json.null,
        }
    end

    -- Herblores serialise their CURRENT phase: name/type/expires_at/
    -- expected_duration let the pane render them as ordinary buff/debuff cells.
    -- key is unused until PR 2's add-view toggle.
    local herblores = state.char.herblores or {}
    local herblores_out = {}
    for _, e in ipairs(herblores) do
        herblores_out[#herblores_out + 1] = {
            key               = e.key,
            name              = e.name,
            type              = e.type,
            expires_at        = e.expires_at,
            expected_duration = e.expected_duration,
        }
    end

    -- Static catalog keys for PR 2's add-view. herblores.lua (h) loads before
    -- this file (t) alphabetically, so herblore_catalog_keys is normally defined
    -- when the initial serialize runs; the guard is now defensive only (kept in
    -- case the global is ever absent) and no longer load-bearing.
    local herblore_catalog =
        (type(herblore_catalog_keys) == "function") and herblore_catalog_keys() or {}

    local payload = {
        affects          = affects_out,
        stored_spells    = stored_out,
        blinds           = blinds_out,
        charms           = charms_out,
        herblores        = herblores_out,
        herblore_catalog = herblore_catalog,
    }
    local ok, encoded = pcall(json.encode, payload)
    if not ok then
        dbg("[TIMERS_STATE] encode failed: " .. tostring(encoded))
        return
    end
    local f, err = io.open(TMP_PATH, "w")
    if not f then
        dbg("[TIMERS_STATE] open tmp failed: " .. tostring(err))
        return
    end
    f:write(encoded)
    f:close()
    os.rename(TMP_PATH, STATE_PATH)
end

-- Fire on every affect or stored-spell change, reset, or new character name.
-- affects.lua subscribes to gmcp_char_name before this file (alphabetical),
-- so _load_active() results are in state.char.affects when our subscriber runs.
events.subscribe("affects_changed",        serialize)
events.subscribe("stored_spells_changed",  serialize)
events.subscribe("blinds_changed",         serialize)
events.subscribe("charms_changed",         serialize)
events.subscribe("herblores_changed",      serialize)
events.subscribe("char_reset",             function() serialize() end)
events.subscribe("gmcp_char_name",         function() serialize() end)

-- Initial write so the renderer has a file on first start. This is correct
-- precisely because this module loads last (after all producers have restored):
-- the subscriber above loads after the producers' restore-time emits, so without
-- this call timers.state would stay empty until the first runtime *_changed emit.
serialize()

dbg("[TIMERS_STATE] loaded")
