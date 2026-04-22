-- Passive communication logger.
-- Appends every Comm.Channel event to state.comm.history (ring buffer).
-- No alias, no register_script — background collector only.
-- body.text is stored verbatim (ANSI codes preserved for future search/filter UI).

gmcp.handlers["Comm.Channel"] = function(body)
    body = body or {}
    local entry = {
        ts      = os.time(),
        channel = body.channel,
        talker  = body.talker,
        text    = body.text,
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

dbg("[COMM_LOG] loaded")
