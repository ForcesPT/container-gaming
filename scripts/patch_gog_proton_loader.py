#!/usr/bin/python3
"""Select GE11's native 64-bit Unix loader only for the official Galaxy client."""
from pathlib import Path
import re
import sys

proton = Path(sys.argv[1])
source = proton.read_text()
needle = r'^        self\.wine_bin = self\.bin_dir \+ "wine"$'
addition = '''        self.wine_bin = self.bin_dir + "wine"
        # Galaxy's legacy loader path reproduced native heap failures during
        # cold startup. Other stores, installers and games keep the vendor path.
        if (os.environ.get("DPAD_GOG_NATIVE64") == "1"
                and os.environ.get("STORE") == "gog"
                and platform.machine() == "x86_64" and len(sys.argv) > 2
                and sys.argv[2].replace("\\\\", "/").rsplit("/", 1)[-1].casefold() == "galaxyclient.exe"):
            candidate = self.lib_dir + "wine/x86_64-unix/wine64"
            if not os.access(candidate, os.X_OK):
                raise RuntimeError("Galaxy native loader is unavailable")
            self.wine_bin = candidate'''
if source.count(addition) == 1:
    raise SystemExit(0)
if 'DPAD_GOG_NATIVE64' in source or len(re.findall(needle, source, re.MULTILINE)) != 1:
    raise SystemExit('Pinned GE11 loader initialization mismatch')
# Use a callable replacement so Python's regex engine preserves backslashes.
source = re.sub(needle, lambda match: addition, source, flags=re.MULTILINE)
compile(source, str(proton), 'exec')
proton.write_text(source)
