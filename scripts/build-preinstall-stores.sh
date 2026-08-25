#!/bin/bash
# Build all Windows store clients into one sanitized image layer.
# Usage: docker run --privileged --name dpad-store-bake --entrypoint \
#   /opt/dpadcloud/build-preinstall-stores.sh <base-image>
# Then verify the success marker and docker commit the container once.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "must run as root" >&2; exit 2; }

PREFIX_BNET="/opt/dpadcloud/battlenet-prefix"
PREFIX_EA="/opt/dpadcloud/ea-prefix"
PREFIX_UBISOFT="/opt/dpadcloud/ubisoft-prefix"
READY=/opt/dpadcloud/.preinstalled-stores-ready
rm -f "$READY"

/opt/dpadcloud/build-bootstrap-battlenet.sh
/opt/dpadcloud/build-bootstrap-ea.sh
/opt/dpadcloud/build-bootstrap-ubisoft.sh

valid_pe() {
  /opt/dpadcloud/dpad-verify-windows-binary --pe-only "$1" >/dev/null 2>&1
}
bnet_exe() {
  valid_pe "$PREFIX_BNET/drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe" ||
    valid_pe "$PREFIX_BNET/drive_c/Program Files (x86)/Battle.net/Battle.net.exe"
}
ea_exe() {
  local candidate
  valid_pe "$PREFIX_EA/drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop/EADesktop.exe" && return 0
  valid_pe "$PREFIX_EA/drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop/EALauncher.exe" && return 0
  while IFS= read -r -d '' candidate; do
    valid_pe "$candidate" && return 0
  done < <(find "$PREFIX_EA/drive_c/Program Files/Electronic Arts/EA Desktop" -type f \
    \( -path '*/EA Desktop/EADesktop.exe' -o -path '*/EA Desktop/EALauncher.exe' \) -print0 2>/dev/null)
  return 1
}
ubisoft_exe() {
  valid_pe "$PREFIX_UBISOFT/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe" ||
    valid_pe "$PREFIX_UBISOFT/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/upc.exe"
}

bnet_exe || { echo "valid Battle.net launcher missing after preinstall" >&2; exit 1; }
ea_exe || { echo "valid EA Desktop launcher missing after preinstall" >&2; exit 1; }
ubisoft_exe || { echo "valid Ubisoft Connect launcher missing after preinstall" >&2; exit 1; }

sanitize_prefix() {
  local prefix="$1"
  /opt/dpadcloud/dpad-sanitize-store-prefix "$prefix"
  /opt/dpadcloud/dpad-randomize-prefix-id --template "$prefix"
  rm -f "$prefix/.dpad-prebaked" "$prefix/.dpad-preinstalled"
  touch "$prefix/.dpad-preinstalled"
  chown -R dpad:dpad "$prefix"
}

sanitize_prefix "$PREFIX_BNET"
sanitize_prefix "$PREFIX_EA"
sanitize_prefix "$PREFIX_UBISOFT"

# The shared UMU/SLR runtime is retained once in this committed container.
chown -R dpad:dpad /home/dpad/.local/share/umu 2>/dev/null || true
touch "$READY"
echo PREINSTALLED_STORES_READY
