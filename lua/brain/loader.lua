-- lua/brain/loader.lua
-- Exports: load_scripts
-- Depends on: dbg (ui.lua), _register_cockpit_help, _write_scripts_cache (registry.lua)

-- Loads lua/core/*.lua then lua/scripts/*.lua via dofile.
-- Returns n_core, n_scripts counts.
function load_scripts()
    local n_core, n_scripts = 0, 0
    local function load_dir(glob)
        local count = 0
        local p = io.popen("ls " .. glob .. " 2>/dev/null")
        if p then
            for f in p:lines() do
                dofile(f)
                count = count + 1
            end
            p:close()
        end
        return count
    end
    n_core    = load_dir("lua/core/*.lua")
    n_scripts = load_dir("lua/scripts/*.lua")
    _register_cockpit_help()
    _write_scripts_cache()
    return n_core, n_scripts
end
