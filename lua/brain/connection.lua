-- lua/brain/connection.lua
-- Exports: GAME_SESSION, mark_mume_connected, mark_mume_disconnected,
--          set_game_session, clear_game_session, _clear_connection_state
-- Depends on: system_ui, ui_var, dbg (ui.lua), tintin_cmd, tintin (io.lua)

local CONNECTION_STATE_PATH = "bridge/runtime/connection.state"
local USER_RECONNECT_PATH   = "bridge/runtime/.user_reconnecting"

GAME_SESSION = nil  -- set dynamically when a game session connects

local function _write_connection_state()
    local tmp = CONNECTION_STATE_PATH .. ".tmp"
    local f   = io.open(tmp, "w")
    if not f then return end
    f:write(string.format("connected_at=%d\n", os.time()))
    f:close()
    os.rename(tmp, CONNECTION_STATE_PATH)
end

function _clear_connection_state()
    os.remove(CONNECTION_STATE_PATH)
end

-- User-initiated reconnect sentinel. Set by the reconnect alias before the
-- disconnect step; single-shot eaten by mark_mume_disconnected() so the
-- transient disconnect signal does not auto-open the popup mid-reconnect.
local function _mark_user_reconnecting()
    local f = io.open(USER_RECONNECT_PATH, "w")
    if f then f:close() end
end

local function _clear_user_reconnecting()
    os.remove(USER_RECONNECT_PATH)
end

local function _is_user_reconnecting()
    local f = io.open(USER_RECONNECT_PATH, "r")
    if f then f:close(); return true end
    return false
end

function mark_user_reconnecting()  _mark_user_reconnecting()  end
function clear_user_reconnecting() _clear_user_reconnecting() end

local function _popup_is_open()
    local f = io.open("bridge/runtime/.popup_open", "r")
    if f then f:close(); return true end
    return false
end

local function _open_popup()
    os.execute('tmux display-popup -E -w 80% -h 80% -x C -y C -S fg=#008787 "bash $HOME/MUME/bridge/launcher/ingame_menu.sh" >/dev/null 2>&1 &')
end

-- mark_mume_connected() / mark_mume_disconnected() — idempotent, transition-only.
-- Drive bridge/runtime/connection.state from GMCP (Char.Name → connected, Core.Goodbye → disconnected).
-- Only act (and only emit system_ui) on the actual state change; detect via file existence.
function mark_mume_connected()
    local f = io.open(CONNECTION_STATE_PATH, "r")
    if f then f:close(); return end
    _write_connection_state()
    local name = state.char.name or "Character"
    system_ui(ui_var(name) .. " logged in.")
    events.emit("run_started")
    if state.run and state.run.reset then state.run.reset() end
end

function mark_mume_disconnected()
    local f = io.open(CONNECTION_STATE_PATH, "r")
    if not f then return end
    f:close()
    _clear_connection_state()
    local name = state.char.name or "Character"
    system_ui(ui_var(name) .. " logged out.")
    if _is_user_reconnecting() then
        _clear_user_reconnecting()
    elseif not _popup_is_open() then
        _open_popup()
    end
    events.emit("run_ending")
    if state.run and state.run.reset then state.run.reset() end
    if state.char and state.char.reset then state.char.reset() end
end

function set_game_session(ses)
    GAME_SESSION = ses
    system_ui("Connecting to MUME...")
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
        system_ui("Connection to MUME closed.")
        tintin("gts", "#unvar game_session")
    else
        dbg("clear_game_session: mismatch")
    end
end
