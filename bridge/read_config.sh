#!/bin/bash
# bridge/read_config.sh — reads bridge/startup.conf and prints tt++ variable assignments.
# Called by ttpp/core/config.tin via #script at startup.
# Falls back to sane defaults if startup.conf is missing.

CONF="bridge/startup.conf"
if [ -f "$CONF" ]; then
    . "$CONF"
fi
: "${profile:=default}"
: "${connection_mode:=mmapper}"
case "$connection_mode" in
    direct) host=mume.org  ;;
    *)      host=localhost ;;
esac
echo "#var {_profile} {$profile}"
echo "#var {_host}    {$host}"
echo "#var {_port}    {4242}"
