-- Passive communication logger.
-- Handles Comm.Channel.Text (message history, ring-buffered) and
-- Comm.Channel.List (channel enabling via gmcp_enable_channel alias).
-- No alias, no register_script — background collector only.
-- body.text is stored verbatim (ANSI codes preserved for future search/filter UI).

gmcp.handlers["Comm.Channel.Text"] = function(body)
    body = body or {}
    local entry = {
        ts          = os.time(),
        channel     = body.channel,
        destination = body.destination,
        talker      = body.talker,
        talker_type = body["talker-type"],
        text        = body.text,
    }
    local hist = state.comm.history
    hist[#hist + 1] = entry
    -- NOTE: table.remove(t, 1) is O(n). Fine for max_size=500 and
    -- expected message rates. If volume grows, convert to a head-index
    -- ring buffer.
    while #hist > state.comm.max_size do
        table.remove(hist, 1)
    end
end

gmcp.handlers["Comm.Channel.List"] = function(body)
    body = body or {}
    state.comm.channels = body
    for _, ch in ipairs(body) do
        if ch.name then
            session_cmd(string.format(
                "gmcp_enable_channel {%s}", ch.name))
        end
    end
end

dbg("[COMM_LOG] loaded")
