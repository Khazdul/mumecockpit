-- lua/brain/events.lua
-- Exports: events (handlers, subscribe, unsubscribe, emit, trace, trace_skip)
-- Depends on: dbg (ui.lua)

events = {
    handlers   = {},
    trace      = true,
    trace_skip = { clock_changed = true, gmcp_char_vitals = false },
}

function events.subscribe(name, fn)
    if not events.handlers[name] then
        events.handlers[name] = {}
    end
    local t = events.handlers[name]
    t[#t+1] = fn
    return fn
end

function events.unsubscribe(name, fn)
    local t = events.handlers[name]
    if not t then return end
    for i = #t, 1, -1 do
        if t[i] == fn then
            table.remove(t, i)
        end
    end
end

function events.emit(name, ...)
    local t = events.handlers[name]
    if events.trace and not events.trace_skip[name] then
        local n = select("#", ...)
        if n == 0 then
            dbg("[EVENTS] " .. name)
        else
            local parts = {}
            for i = 1, n do parts[i] = tostring(select(i, ...)) end
            dbg("[EVENTS] " .. name .. " = " .. table.concat(parts, ", "))
        end
    end
    if not t then return end
    for _, fn in ipairs(t) do
        local ok, err = pcall(fn, ...)
        if not ok then
            dbg("events handler error [" .. name .. "]: " .. tostring(err))
        end
    end
end
