#!/usr/bin/env bash
# Compat shim — moved to bridge/launcher/ in v0.7.0. Remove once
# all clients have updated past this release.
exec bash "$(cd "$(dirname "$0")" && pwd)/launcher/$(basename "$0")"
