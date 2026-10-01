#!/usr/bin/python3
"""Exercise the actual patched vendor constructor without starting any client."""
import ast
import os
from pathlib import Path
import platform
import sys

runner = Path(sys.argv[1])
tree = ast.parse((runner / 'proton').read_text())
constructor = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Proton')
namespace = dict(os=os, platform=platform, sys=sys, FileLock=lambda *a, **k: None,
                 file_exists=lambda p, **k: Path(p).exists())
exec(compile(ast.Module(body=[constructor], type_ignores=[]), '<vendor Proton constructor>', 'exec'), namespace)
for store, flag, executable, native in [
    ('gog', '1', r'C:\Program Files\GOG Galaxy\GalaxyClient.exe', True),
    ('gog', '0', r'C:\Program Files\GOG Galaxy\GalaxyClient.exe', False),
    ('epic', '1', r'C:\Program Files\GOG Galaxy\GalaxyClient.exe', False),
    ('gog', '1', r'C:\Games\Game.exe', False),
    ('gog', '1', r'C:\Installers\GOGGalaxy.exe', False),
]:
    os.environ.update(STORE=store, DPAD_GOG_NATIVE64=flag)
    sys.argv = ['proton', 'waitforexitandrun', executable]
    selected = namespace['Proton'](str(runner)).wine_bin
    expected = runner / ('files/lib/wine/x86_64-unix/wine64' if native else 'files/bin/wine')
    assert selected == str(expected), (store, flag, executable, selected)
    print(f'GOG_NATIVE_LOADER_SCOPE_PASS store={store} enabled={flag} native={native}')
