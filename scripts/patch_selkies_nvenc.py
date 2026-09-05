#!/usr/bin/env python3
"""Add an explicit modern H.264 branch without rewriting legacy settings.

Patches the installed 1.6.2 module, retaining existing Wayland/input patches.
AST locates only the relevant lists/branch; unrelated source stays byte-identical.
"""
import ast
from pathlib import Path
import sys


def patch(source):
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    candidates = [c for c in classes if any(isinstance(n, ast.FunctionDef) and
                  n.name == 'build_video_pipeline' for n in c.body)]
    if len(candidates) != 1:
        raise ValueError('expected one Selkies video pipeline class')
    cls = candidates[0]
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    if not {'check_plugins', 'set_video_bitrate', 'set_framerate'} <= methods.keys():
        raise ValueError('unsupported Selkies methods')
    if 'DPAD_MODERN_NVENC = True' in source:
        modern_lists = [n for n in ast.walk(cls) if isinstance(n, ast.List)
                        and any(isinstance(v, ast.Constant) and v.value == 'nvcudah264enc' for v in n.elts)]
        if (source.count('from dpad_nvenc import build_modern_tail') != 1
                or len(modern_lists) < 2
                or 'check_profile(self)' not in source
                or 'build_modern_tail(Gst, self)' not in source):
            raise ValueError('partial modern NVENC patch')
        return source
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    def span(node):
        return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset
    edits = []
    branches = [n for n in methods['build_video_pipeline'].body if isinstance(n, ast.If)
                and ast.unparse(n.test) == "self.encoder in ['nvh264enc']"]
    if len(branches) != 2:
        raise ValueError('expected encoder construction and assembly branches')
    first = branches[0]
    start, _ = span(first)
    edits.append((start, start + 2,
        'if self.encoder == "nvcudah264enc":\n'
        '            from dpad_nvenc import build_modern_tail\n'
        '            cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc = build_modern_tail(Gst, self)\n'
        '        elif'))
    count = 0
    for node in ast.walk(cls):
        if isinstance(node, ast.List) and any(isinstance(v, ast.Constant) and v.value == 'nvh264enc' for v in node.elts):
            if node is first.test.comparators[0]:
                continue
            start, end = span(node)
            edits.append((end - 1, end - 1, ', "nvcudah264enc"'))
            count += 1
    if count < 2:
        raise ValueError('missing assembly/supported encoder lists')
    check = methods['check_plugins']
    start = offsets[check.body[0].lineno - 1]
    edits.append((start, start,
        '        from dpad_nvenc import check_profile\n'
        '        check_profile(self)\n'))
    # Marker is a class attribute usable by the preflight without source reads.
    start = offsets[cls.body[0].lineno - 1]
    edits.append((start, start, '    DPAD_MODERN_NVENC = True\n'))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    ast.parse(source)
    return source


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py')
    try:
        original = path.read_text()
        result = patch(original)
        path.write_text(result)
    except Exception as error:
        print(f'patch_selkies_nvenc: {error}', file=sys.stderr)
        sys.exit(1)
