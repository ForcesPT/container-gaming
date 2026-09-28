#!/usr/bin/python3
"""Pinned 2.4.2 adapter: use image UMU and honour disabled component updates."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
path = root / 'faugus/path_manager.py'
source = path.read_text()
old = "UMU_RUN = PathManager.user_data('faugus-launcher/umu-run')"
if source.count(old) != 1:
    raise SystemExit('Unexpected Faugus UMU path')
path.write_text(source.replace(old, "UMU_RUN = '/usr/bin/umu-run'"))
path = root / 'faugus/runner.py'
source = path.read_text()
old = 'if not os.environ.get("DISABLE_UMU") and (not force_off or not self.components_exists):'
if source.count(old) != 1:
    raise SystemExit('Unexpected Faugus update branch')
path.write_text(source.replace(old, 'if not os.environ.get("DISABLE_UMU") and not force_off:'))
source = path.read_text()
old = '        GLib.idle_add(finish)\n        kill_child_proc()\n'
new = '''        if self.gameid == "dpad-epic":
            from faugus.dpad_epic_handoff import wait_for_epic_exit
            print("dpad-epic: UMU parent exited; allowing Epic process handoff", flush=True)

            def finish_after_handoff():
                print("dpad-epic: Epic processes are quiet; finalizing", flush=True)
                GLib.idle_add(finish)
                kill_child_proc()

            Thread(target=wait_for_epic_exit, args=(finish_after_handoff,), daemon=True).start()
        else:
            GLib.idle_add(finish)
            kill_child_proc()
'''
if source.count(old) != 1:
    raise SystemExit('Unexpected Faugus process exit hook')
path.write_text(source.replace(old, new))
shutil.copyfile('/tmp/dpad_epic_handoff.py', root / 'faugus/dpad_epic_handoff.py')
