#!/bin/sh
set -eu

mkdir -p /app/data /tmp/vxd3v-converter
chown -R bot:bot /app/data /tmp/vxd3v-converter

exec gosu bot "$@"
