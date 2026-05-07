#!/usr/bin/env bash
# bridge/services/read_version.sh — reads VERSION and emits a tt++ #var command.
# Called by ttpp/core/gmcp.tin via #script at startup.
# Falls back to "dev" if VERSION is missing.

VERSION="dev"
if [ -f VERSION ]; then
    VERSION=$(tr -d '\n' < VERSION)
fi
echo "#var {_client_version} {$VERSION}"
