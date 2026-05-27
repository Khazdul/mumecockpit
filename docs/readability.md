# Readability

Drop-in `.tin` modules that alter how MUD output looks — highlights,
substitutes, gags — toggled per user via `startup.conf`. Each module is a
plain TinTin++ file; adding one is a file drop with no code changes.

Touch this file when adding a module, changing the loader contract, or
modifying the `.meta` format.

## Directory layout

```
ttpp/readability/
  modules/
    example.tin        module file — #highlight, #substitute, etc.
    example.meta       optional metadata (TOML) — UI description + preview
    <name>.tin         drop a file here to create a new module
    <name>.meta        optional companion metadata
```

Modules are discovered by filename: the stem of each `.tin` file is the
module name. A module named `foo` lives at `ttpp/readability/modules/foo.tin`.

## `.meta` format

Optional companion file for each module. Format: TOML. Used by the
launcher and in-game popup to describe the module to the user. Slice 1
does not parse `.meta` — the file exists as a format reference.

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | One-sentence summary of what the module does. |
| `example_before` | array of strings | Up to 6 lines showing MUD output *without* the module. Plain text. |
| `example_after` | array of strings | Up to 6 lines showing MUD output *with* the module. May contain raw ANSI escape sequences (`[...m`) for FG/BG colour and styling. |

The 6-line soft cap keeps the preview compact in the UI. ANSI sequences
in `example_after` are rendered literally by the terminal — the popup
preview writes them directly.

## Loader contract

Three tt++ aliases manage the `{readability}` class. Defined in
`ttpp/core/readability.tin` (auto-loaded into gts by `main.tin`).

| Alias | Purpose |
|-------|---------|
| `readability_load <list>` | Open `{readability}`, `#foreach` + `#read` each module, close the class. `<list>` is semicolon-separated module names. |
| `readability_clear` | `#class {readability} {kill}` — destroy the class and all its members. |
| `readability_reload <list>` | `readability_clear` then `readability_load` — atomic refresh. |

Each alias body is a single tt++ statement (semicolon-separated commands
on one line). The class open/read/close sequence lives entirely within the
alias — never synthesized across multiple relay lines. This follows the
atomicity principle from ADR 0097: no foreign `#class` operation in another
session can interleave.

The `{readability}` class is **never** opened or closed outside these
aliases.

## Lifecycle

### Cold load (session start)

`lua/scripts/readability.lua` subscribes to the `run_started` event.
When the player logs in (`Char.Name` GMCP fires):

1. Read `bridge/runtime/startup.conf` for the `readability_enabled` key.
2. Parse the comma-separated module names, validate each against
   `ttpp/readability/modules/<name>.tin`. Unknown names that don't
   correspond to an existing `.tin` file are silently filtered out
   (removing a file from disk doesn't break next session); a
   `ui_warn()` is emitted for each missing module.
3. If the resolved list is non-empty, issue
   `session_cmd("readability_load {a;b;c}")` — commas from the conf
   are translated to semicolons for `#foreach` ergonomics.
4. If the list is empty, skip the call entirely (no empty class created).

### Hot reload (manual / popup-triggered)

Call `scripts.readability.reload()` from tt++ via
`#lua {scripts.readability.reload()}`. This:

1. Re-reads `startup.conf` for `readability_enabled`.
2. Validates the module list.
3. Issues `session_cmd("readability_reload {a;b;c}")` (or
   `readability_clear` if the list is now empty).

Slice 2's popup will fire this automatically after the user toggles
modules. In slice 1, trigger it manually for verification.

## startup.conf integration

| Key | Default | Description |
|-----|---------|-------------|
| `readability_enabled` | *(empty)* | Comma-separated module names to load. Empty = all modules off. |

The key lives in `bridge/launcher/templates/startup.conf` (ADR 0101
single source of truth for fresh-install seeding). A fresh install
starts with all readability modules off.

## Authoring a new module

1. Create `ttpp/readability/modules/<name>.tin` with your `#highlight`,
   `#substitute`, `#gag`, or other tt++ rules.
2. Optionally create `ttpp/readability/modules/<name>.meta` with the
   TOML metadata (description + before/after preview).
3. No code changes needed — the loader discovers modules by filename.
4. Enable the module by adding its name to `readability_enabled` in
   `bridge/runtime/startup.conf` (comma-separated if multiple).
5. Reload: either restart the session, or fire
   `#lua {scripts.readability.reload()}` for a hot reload.

---
Back to [architecture.md](../architecture.md).
