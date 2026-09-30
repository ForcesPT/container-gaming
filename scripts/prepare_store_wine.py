#!/usr/bin/python3
"""Run the pinned upstream Wine preparation, excluding unrelated submodules."""
from pathlib import Path

upstream = Path('/src/ge/patches/protonprep-valve-staging.sh').read_text()
start = upstream.index('### (2) WINE PATCHING ###')
end = upstream.index('### END WINE PATCHING ###', start)
wine = upstream[start:end]
assert wine.count('git revert --no-commit e813ca5771658b00875924ab88d525322e50d39f') == 1
wine = wine.replace('git revert --no-commit e813ca5771658b00875924ab88d525322e50d39f',
                    'git apply -R /tmp/restore-configure.patch')
# This patch partially reapplies an existing gameinput Makefile and configure entry
# in the pinned tree. It affects only the gameinput DLL, which we never rebuild.
# The published runner's DLL remains intact; keep server changes fail-closed.
gameinput = '    apply_patch "../patches/game-patches/lemansultimate-gameinput.patch"'
assert wine.count(gameinput) == 1
wine = wine.replace(gameinput, '    echo "Retaining published gameinput DLL"')
Path('/src/patches').symlink_to('/src/ge/patches', target_is_directory=True)
Path('/tmp/prepare-store-wine.sh').write_text(
    '#!/bin/bash\nset -euo pipefail\n'
    'apply_patch() { if grep -q "^GIT binary patch" "$1"; then git apply --binary "$1"; '
    'else patch -Np1 < "$1" || git apply --reverse --check "$1"; fi; }\n'
    'apply_all_in_dir() { for p in "$1"/*.patch; do apply_patch "$p"; done; }\n' + wine)
