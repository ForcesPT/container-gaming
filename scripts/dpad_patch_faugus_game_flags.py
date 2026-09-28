#!/usr/bin/env python3
"""Forward diagnostic flags through pinned Faugus's --game shell shortcut."""

from pathlib import Path


source = Path('/opt/dpadcloud/faugus/source/faugus-launcher')
runner = Path('/opt/dpadcloud/faugus/source/faugus/runner.py')
old = '--game)     exec /usr/bin/python3 -m faugus.runner --game "$2";;'
new = '--game)     game="$2"; shift 2; exec /usr/bin/python3 -m faugus.runner --game "$game" "$@";;'

text = source.read_text()
if text.count(old) != 1 or text.count(new) != 0:
    raise SystemExit('pinned Faugus --game shortcut changed')
if 'parser.add_argument("--logs", action="store_true")' not in runner.read_text():
    raise SystemExit('pinned Faugus runner no longer accepts --logs')
source.write_text(text.replace(old, new, 1))
