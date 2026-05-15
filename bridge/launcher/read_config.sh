#!/usr/bin/env bash
# bridge/launcher/read_config.sh — reads bridge/runtime/startup.conf and prints tt++ variable assignments.
# Called by ttpp/core/config.tin via #script at startup.
# Falls back to sane defaults if startup.conf is missing.

CONF="bridge/runtime/startup.conf"
if [ -f "$CONF" ]; then
    . "$CONF"
fi
: "${profile:=default}"
: "${connection_mode:=mmapper}"
: "${show_buffs:=0}"
: "${connection_host:=localhost}"
: "${connection_port:=4242}"
case "$connection_mode" in
    direct) host=mume.org           ; port=4242              ; ses_cmd=ssl ;;
    custom) host="$connection_host" ; port="$connection_port"; ses_cmd=ses ;;
    *)      host=localhost          ; port=4242              ; ses_cmd=ses ;;
esac
echo "#var {_profile}   {$profile}"
echo "#var {_host}      {$host}"
echo "#var {_port}      {$port}"
echo "#var {_ses_cmd}   {$ses_cmd}"
echo "#var {show_buffs} {$show_buffs}"
