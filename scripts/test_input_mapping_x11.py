"""Real local X11 map changes through packaged Selkies input; no account/media."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def scenario(desktop):
    os.environ.update(DISPLAY=':17',DPAD_INPUT_DISPLAY=':17',DPAD_DESKTOP_CLIENT=desktop)
    os.environ.pop('DPAD_INPUT_DEBUG',None)
    server=subprocess.Popen(['Xvfb',':17','-screen','0','640x480x24','-nolisten','tcp','-ac'],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        from Xlib import X,XK,display
        from Xlib.protocol import event
        for _ in range(100):
            try:
                receiver=display.Display(':17');break
            except Exception:time.sleep(.05)
        else:raise RuntimeError('local X11 unavailable')
        window=receiver.screen().root.create_window(0,0,200,100,0,receiver.screen().root_depth,
            X.InputOutput,X.CopyFromParent,event_mask=X.KeyPressMask|X.KeyReleaseMask)
        window.map();window.set_input_focus(X.RevertToParent,X.CurrentTime);receiver.sync()
        def layout(code):
            subprocess.run(['setxkbmap','-display',':17','-layout',code],check=True,capture_output=True,timeout=5)
            info=receiver.display.info
            receiver.refresh_keyboard_mapping(event.MappingNotify(request=X.MappingKeyboard,first_keycode=info.min_keycode,
                count=info.max_keycode-info.min_keycode+1))
        layout('us')
        import selkies_gstreamer
        sys.path.insert(0,str(Path(selkies_gstreamer.__file__).parent))
        import webrtc_input
        # Real client class and real XTest delivery. The Labwc case explicitly
        # exercises its documented XTest fallback, not the production Gst seat.
        import dpad_wayland_input
        dpad_wayland_input.keyboard_key=lambda *_:False
        source=Path(os.environ.get('DPAD_TEST_INPUT_PATCH','/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py'))
        spec=importlib.util.spec_from_file_location('qualified_input',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        client=webrtc_input.WebRTCInput(enable_cursors=False)
        def events(count):
            deadline=time.monotonic()+3;result=[]
            while len(result)<count and time.monotonic()<deadline:
                receiver.sync()
                while receiver.pending_events():
                    value=receiver.next_event()
                    if value.type in (X.KeyPress,X.KeyRelease):result.append(value)
                if len(result)<count:time.sleep(.01)
            assert len(result)==count,(desktop,len(result),count)
            return result
        def equals(shift):
            if shift:client.send_x11_keypress(XK.XK_Shift_L,True)
            client.send_x11_keypress(ord('='),True);client.send_x11_keypress(ord('='),False)
            if shift:client.send_x11_keypress(XK.XK_Shift_L,False)
            keys=events(4 if shift else 2)
            key=keys[1 if shift else 0]
            assert receiver.keycode_to_keysym(key.detail,1 if key.state & X.ShiftMask else 0)==ord('='),(desktop,key.detail,key.state)
            return key.detail
        initial=equals(False)
        layout('pt');portuguese=equals(True)
        assert portuguese!=initial,(initial,portuguese)
        # Change the server map while '=' is held: release must use the actual
        # press keycode, then the next press resolves against the new map.
        client.send_x11_keypress(ord('='),True);pressed=events(1)[0]
        layout('us');client.send_x11_keypress(ord('='),False);released=events(1)[0]
        assert pressed.detail==released.detail==portuguese
        assert equals(False)==initial
        client.send_x11_keypress(ord('a'),True);held=events(1)[0]
        client.reset_keyboard();release=events(1)[0]
        assert held.detail==release.detail and release.type==X.KeyRelease
        assert client._dpad_pressed_keys=={}
        print(json.dumps({'desktop':desktop,'usEqualsKeycode':initial,'ptEqualsKeycode':portuguese,
            'actualSelkiesClass':True,'realXTest':True,'heldReleaseAndReset':True,'nativeWaylandSeatQualified':False}))
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':
    if len(sys.argv)==2:scenario(sys.argv[1])
    else:
        for desktop in ('sway','labwc'):
            subprocess.run([sys.executable,str(Path(__file__).resolve()),desktop],check=True,timeout=30)
