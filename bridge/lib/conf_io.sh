#!/usr/bin/env bash
# bridge/lib/conf_io.sh — portable in-place config file edits.
# The GNU `-i "<expr>" file` form is not portable: BSD/macOS sed treats
# the expression as the backup-suffix argument and emits "undefined
# label" / "invalid command code" errors. Use the temp-file pattern so
# behaviour is identical on both platforms. See ADR 0020.

sed_inplace() {
    local expr="$1" file="$2"
    sed "$expr" "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}
