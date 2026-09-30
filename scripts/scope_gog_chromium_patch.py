#!/usr/bin/python3
"""Restrict the pinned Soju Qt flag compatibility patch to opted-in Galaxy."""
from pathlib import Path

root = Path('/src/wine')
guard = '''    if (GetEnvironmentVariableW(L"DPAD_GOG_SOFTWARE_RENDERING", setting, ARRAY_SIZE(setting)) != 1
        || setting[0] != '1') return{empty};
    len = GetModuleFileNameW(NULL, executable, ARRAY_SIZE(executable));
    if (!len || len >= ARRAY_SIZE(executable)) return{empty};
    base = wcsrchr(executable, '\\\\');
    if (wcsicmp(base ? base + 1 : executable, L"GalaxyClient.exe")) return{empty};
    lstrcpyW(extra, L"--disable-gpu");
    len = lstrlenW(extra);'''
for name, empty in [('dlls/kernelbase/process.c', ' NULL'), ('dlls/msvcrt/environ.c', '')]:
    p = root / name
    text = p.read_text()
    marker = 'GetEnvironmentVariableW'
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if marker in line and 'L"SOJU_CHROMIUM_FLAGS"' in line]
    assert len(matches) == 1, 'Pinned Chromium patch lookup mismatch'
    lines[matches[0]] = guard.format(empty=empty)
    text = '\n'.join(lines) + '\n'
    old = 'WCHAR extra[1024];' if empty else 'wchar_t extra[1024], *nw;'
    new = old + '\n    WCHAR executable[1024], setting[2], *base;'
    assert text.count(old) == 1, 'Pinned Chromium patch declaration mismatch'
    text = text.replace(old, new)
    text = text.replace('Soju: appending SOJU_CHROMIUM_FLAGS to %s', 'DpadPlay: applying Galaxy software renderer to %s')
    p.write_text(text)
