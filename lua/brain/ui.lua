-- lua/brain/ui.lua
-- Exports: dbg, ui, ui_var, script_ui, system_ui, ui_warn, ui_err, char_ui

local UI_LOG    = "logs/ui.log"
local DEBUG_LOG = "logs/debug.log"

local debug_fh  = io.open(DEBUG_LOG, "a")
local ui_log_fh = io.open(UI_LOG, "a")

local _C_SCRIPT = "\027[38;2;38;198;218m"  -- teal  #26C6DA
local _C_TEXT   = "\027[1;97m"             -- bold bright white — base message text
local _C_VAR    = "\027[1;38;2;255;238;88m" -- bold yellow #FFEE58 — dynamic values in ui messages
local _C_SYSTEM = "\027[38;2;66;165;245m"  -- blue #42A5F5 — system events
local _C_WARN   = "\027[38;2;255;179;0m"   -- amber      #FFB300 — warnings
local _C_ERR    = "\027[38;2;229;57;53m"   -- red        #E53935 — errors
local _C_SPELL  = "\027[38;2;122;169;214m"  -- light steel-blue #7AA9D6
local _C_BUFF   = "\027[38;2;143;188;143m"  -- soft sage green  #8FBC8F
local _C_DEBUFF = "\027[38;2;201;112;112m"  -- muted brick red  #C97070
local _C_STORE  = "\027[38;2;179;157;219m"  -- muted lavender   #B39DDB
local _C_BLIND  = "\027[38;2;0;204;204m"    -- cyan             #00CCCC — matches buffs-pane Blinds group
-- _C_HERB  = nil  -- placeholder: colour TBD when herblore tracker lands
-- _C_CHARM = nil  -- placeholder: colour TBD when charm tracker lands
local _C_RESET  = "\027[0m"

function dbg(msg)
    if debug_fh then
        debug_fh:write(os.date("[%H:%M:%S] ") .. msg .. "\n")
        debug_fh:flush()
    end
end

function ui(msg)
    if ui_log_fh then
        ui_log_fh:write(msg .. "\n")
        ui_log_fh:flush()
    end
    dbg("UI: " .. msg)
end

-- script_ui(name, msg) — structured status line for the UI pane.
-- Format:  ▶ NAME: message
-- Use for key state changes only: started, stopped, errors.
-- Not for per-cycle noise or debug detail.
function script_ui(name, msg)
    ui(string.format("%s▶ %s:%s %s%s%s", _C_SCRIPT, name, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_var(v) — wraps a dynamic value (session name, target, reason,
-- filename, etc.) in the variable-highlight style (bold yellow).
--
-- Appends _C_TEXT after the trailing reset so text following the
-- variable continues in the base message colour (bold bright white)
-- rather than falling back to the terminal default. This makes
-- ui_var safe to use mid-message without colour bleed.
function ui_var(v)
    return _C_VAR .. tostring(v) .. _C_RESET .. _C_TEXT
end

-- system_ui(msg) — infrastructure lifecycle events (brain start,
-- game session connect/disconnect, cockpit reload, etc.).
-- Format: ● SYSTEM: message.
function system_ui(msg)
    ui(string.format("%s● SYSTEM:%s %s%s%s", _C_SYSTEM, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_warn(msg) — surface a warning to the UI pane (amber).
-- Use only when the player should see the warning — routine/recoverable
-- issues with no player impact go to dbg() instead.
-- Format: ⚠ WARN: message.
function ui_warn(msg)
    ui(string.format("%s⚠ WARN:%s %s%s%s", _C_WARN, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- ui_err(msg) — surface an error to the UI pane (red).
-- Use only when the player should see the error.
-- Format: ✖ ERROR: message.
function ui_err(msg)
    ui(string.format("%s✖ ERROR:%s %s%s%s", _C_ERR, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- char_ui(category, name, verb, detail?) — character-state lifecycle line for the UI pane.
-- category: "spell" | "buff" | "debuff" | "store" | "blind" — selects prefix colour and tag.
-- name: entity name (rendered with ui_var for the dynamic-value style).
-- verb: "up" | "refreshed" | "expiring" | "down", or domain verbs ("stored", "recalled", "decayed", …).
-- detail (optional): appended in parentheses — e.g. "89:58 — sample recorded".
-- Format: ◆ TAG: name verb.   or   ◆ TAG: name verb (detail).
function char_ui(category, name, verb, detail)
    local colour, tag
    if category == "spell" then
        colour, tag = _C_SPELL, "SPELL"
    elseif category == "buff" then
        colour, tag = _C_BUFF, "BUFF"
    elseif category == "debuff" then
        colour, tag = _C_DEBUFF, "DEBUFF"
    elseif category == "store" then
        colour, tag = _C_STORE, "STORE"
    elseif category == "blind" then
        colour, tag = _C_BLIND, "BLIND"
    else
        colour, tag = _C_SCRIPT, "AFFECT"  -- defensive fallback
    end
    if detail then
        ui(string.format("%s◆ %s:%s %s%s %s (%s).%s",
            colour, tag, _C_RESET, _C_TEXT, ui_var(name), verb, detail, _C_RESET))
    else
        ui(string.format("%s◆ %s:%s %s%s %s.%s",
            colour, tag, _C_RESET, _C_TEXT, ui_var(name), verb, _C_RESET))
    end
end
