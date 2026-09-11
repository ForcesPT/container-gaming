#!/bin/sh
# Run in each independent Ubuntu build stage; never disable TLS/signature checks.
set -eu
root=${1:-/etc/apt}
for source in "$root/sources.list" "$root"/sources.list.d/*.list "$root"/sources.list.d/*.sources; do
 [ -f "$source" ] || continue
 sed -i -e 's|http://archive.ubuntu.com/|https://archive.ubuntu.com/|g' -e 's|http://security.ubuntu.com/|https://security.ubuntu.com/|g' "$source"
done
mkdir -p "$root/apt.conf.d"
printf '%s\n' 'APT::Update::Error-Mode "any";' 'Acquire::Retries "3";' 'Acquire::http::Timeout "30";' 'Acquire::https::Timeout "30";' > "$root/apt.conf.d/80dpad-build-network"
