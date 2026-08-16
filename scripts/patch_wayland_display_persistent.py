#!/usr/bin/env python3
"""Keep gst-wayland-display's compositor alive while its source is stopped."""
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

old = '''    fn stop(&self) -> Result<(), gst::ErrorMessage> {
        let mut state = self.state.lock().unwrap();
        if let Some(state) = state.take() {
            let subscriber = Registry::default().with(GstLayer);
            tracing::subscriber::with_default(subscriber, || drop(state.display));
        }
        Ok(())
    }
'''
new = '''    fn stop(&self) -> Result<(), gst::ErrorMessage> {
        // DPAD: preserve the compositor across WebRTC peer disconnects. Selkies
        // keeps this source element referenced and reuses it for the next peer;
        // dropping the element still drops State and shuts the compositor down.
        let _state = self.state.lock().unwrap();
        tracing::info!("Preserving Wayland display while source is stopped");
        Ok(())
    }
'''

if new in source:
    print("patch_wayland_display_persistent: already patched")
elif old in source:
    path.write_text(source.replace(old, new, 1))
    print("patch_wayland_display_persistent: patched stop lifecycle")
else:
    raise SystemExit("patch_wayland_display_persistent: expected pinned stop() source not found")
