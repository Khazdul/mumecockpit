-- Event bus — subscribe/emit/unsubscribe for Lua-side fan-out.
-- Namespace pre-declared in brain.lua; methods added here at core-load time.

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
    if events.trace then
        local args = {...}
        local strs = {}
        for _, v in ipairs(args) do strs[#strs+1] = tostring(v) end
        dbg(string.format("[EVENTS] %s = %s", name, table.concat(strs, ", ")))
    end
    if not t then return end
    for _, fn in ipairs(t) do
        local ok, err = pcall(fn, ...)
        if not ok then
            dbg("events handler error [" .. name .. "]: " .. tostring(err))
        end
    end
end

dbg("[EVENTS] loaded")
