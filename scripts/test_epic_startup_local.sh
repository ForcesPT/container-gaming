#!/bin/bash
# Disposable local image only. No account or GPU validation.
set -euo pipefail
image_scripts=/workspace/scripts
python3 "$image_scripts/test_epic_resume.py"
python3 "$image_scripts/test_epic_restore_dispatch.py"
python3 "$image_scripts/test_faugus_prepare.py"
python3 "$image_scripts/test_epic_updater_failed.py"
ELECTRON_RUN_AS_NODE=1 /opt/dpadcloud/launcher/dpad-launcher \
    "$image_scripts/test_epic_reopen.cjs" /opt/dpadcloud/launcher/resources/app.asar/src/epic_reopen.cjs
ELECTRON_RUN_AS_NODE=1 /opt/dpadcloud/launcher/dpad-launcher "$image_scripts/test_faugus_picker.cjs"
cp /opt/dpadcloud/faugus-epic-launch /tmp/faugus-epic-launch-new
cp /opt/dpadcloud/dpad_faugus_prepare.py /tmp/dpad_faugus_prepare-new.py
cp /opt/dpadcloud/dpad_epic_updater_failed.py /tmp/dpad_epic_updater_failed-new.py
cp /opt/dpadcloud/dpad_epic_resume.py /tmp/dpad_epic_resume-new.py
sed 's/\r$//' "$image_scripts/test_faugus_retry.sh" >/tmp/test_faugus_retry.sh
bash /tmp/test_faugus_retry.sh
