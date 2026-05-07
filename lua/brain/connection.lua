-- lua/brain/connection.lua
-- Exports: GAME_SESSION, mark_mume_connected, mark_mume_disconnected,
--          set_game_session, clear_game_session, _clear_connection_state,
--          _read_startup_conf_value
-- Depends on: system_ui, ui_var, dbg (ui.lua), tintin_cmd, tintin (io.lua)

local CONNECTION_STATE_PATH = "bridge/runtime/connection.state"

GAME_SESSION = nil  -- set dynamically when a game session connects

-- Generic startup.conf key lookup — never sources/executes the file.
-- Can move to its own conf module if more callers appear.
function _read_startup_conf_value(key)
    local f = io.open("bridge/runtime/startup.conf", "r")
    if not f then return nil end
    for line in f:lines() do
        local k, v = line:match("^([^=]+)=(.*)$")
        if k == key then f:close(); return v end
    end
    f:close()
    return nil
end

local function _write_connection_state()
    local mode = _read_startup_conf_value("connection_mode") or "mmapper"
    local tmp  = CONNECTION_STATE_PATH .. ".tmp"
    local f    = io.open(tmp, "w")
    if not f then return end
    f:write(string.format("connected_at=%d\nconnection_mode=%s\n",
                          os.time(), mode))
    f:close()
    os.rename(tmp, CONNECTION_STATE_PATH)
end

function _clear_connection_state()
    os.remove(CONNECTION_STATE_PATH)
end

local function _popup_is_open()
    local f = io.open("bridge/runtime/.popup_open", "r")
    if f then f:close(); return true end
    return false
end

local function _open_popup()
    os.execute('tmux display-popup -E -w 80% -h 80% -x C -y C "bash $HOME/MUME/bridge/launcher/ingame_menu.sh" >/dev/null 2>&1 &')
end

-- mark_mume_connected() / mark_mume_disconnected() — idempotent, transition-only.
-- Drive bridge/runtime/connection.state from GMCP (Char.Name → connected, Core.Goodbye → disconnected).
-- Only act (and only emit system_ui) on the actual state change; detect via file existence.
function mark_mume_connected()
    local f = io.open(CONNECTION_STATE_PATH, "r")
    if f then f:close(); return end
    _write_connection_state()
    system_ui("Connected to MUME.")
    if state.run and state.run.reset then state.run.reset() end
end

function mark_mume_disconnected()
    local f = io.open(CONNECTION_STATE_PATH, "r")
    if not f then return end
    f:close()
    _clear_connection_state()
    system_ui("Disconnected from MUME.")
    if not _popup_is_open() then _open_popup() end
    if state.run and state.run.reset then state.run.reset() end
    if state.char and state.char.reset then state.char.reset() end
end

function set_game_session(ses)
    GAME_SESSION = ses
    system_ui("tt++ session " .. ui_var(ses) .. " open.")
    tintin_cmd("gts", "#var {game_session} {" .. ses .. "}")
end

-- Called when a game session disconnects. Clears GAME_SESSION
-- only if it matches the disconnecting session — guards against
-- stale clears if somehow called with wrong session name.
-- Delegates to mark_mume_disconnected() so the direct-mode abrupt-drop
-- path joins the single dispatch point (popup auto-open, dedup guard).
function clear_game_session(ses)
    if GAME_SESSION == ses then
        GAME_SESSION = nil
        mark_mume_disconnected()
        system_ui("tt++ session " .. ui_var(ses) .. " closed.")
        tintin("gts", "#unvar game_session")
    else
        dbg("clear_game_session: mismatch")
    end
end
