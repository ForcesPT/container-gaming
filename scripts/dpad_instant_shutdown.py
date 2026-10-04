#!/usr/bin/python3
"""Request the sealed selected game's normal X11 close; never kill a process.

This is a best-effort request, not proof of game exit or cloud synchronization.
The host owns the bounded grace deadline and eventual exact-container cleanup.
"""
import ctypes as c
import importlib.util
import json
import os
from pathlib import Path
import sys


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MessageData(c.Union):
    _fields_ = [('bytes', c.c_char * 20), ('longs', c.c_long * 5)]


class ClientMessage(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', MessageData)]


class Event(c.Union):
    _fields_ = [('client', ClientMessage), ('padding', c.c_long * 24)]


class X11:
    def __init__(self, display):
        self.x = c.CDLL('libX11.so.6')
        for name, result, args in [
            ('XOpenDisplay', c.c_void_p, [c.c_char_p]),
            ('XDefaultRootWindow', c.c_ulong, [c.c_void_p]),
            ('XInternAtom', c.c_ulong, [c.c_void_p, c.c_char_p, c.c_int]),
            ('XQueryTree', c.c_int, [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.POINTER(c.c_ulong)), c.POINTER(c.c_uint)]),
            ('XGetWindowProperty', c.c_int, [c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.POINTER(c.c_ubyte))]),
            ('XGetWMProtocols', c.c_int, [c.c_void_p, c.c_ulong, c.POINTER(c.POINTER(c.c_ulong)), c.POINTER(c.c_int)]),
            ('XSendEvent', c.c_int, [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(Event)]),
            ('XGrabServer', c.c_int, [c.c_void_p]), ('XUngrabServer', c.c_int, [c.c_void_p]),
            ('XFlush', c.c_int, [c.c_void_p]), ('XCloseDisplay', c.c_int, [c.c_void_p]),
            ('XFree', c.c_int, [c.c_void_p]),
        ]:
            fn = getattr(self.x, name); fn.restype = result; fn.argtypes = args
        self.display = self.x.XOpenDisplay(display.encode())
        if not self.display:
            raise ValueError('desktop unavailable')
        self.pid_atom = self.x.XInternAtom(self.display, b'_NET_WM_PID', False)
        self.cardinal = self.x.XInternAtom(self.display, b'CARDINAL', False)
        self.protocols = self.x.XInternAtom(self.display, b'WM_PROTOCOLS', False)
        self.delete = self.x.XInternAtom(self.display, b'WM_DELETE_WINDOW', False)

    def close(self):
        if self.display:
            self.x.XCloseDisplay(self.display); self.display = None

    def windows(self):
        queue = [(self.x.XDefaultRootWindow(self.display), 0)]; found = []
        while queue:
            window, depth = queue.pop()
            if len(found) >= 512 or depth >= 32:
                raise ValueError('desktop inventory bound exceeded')
            found.append(window)
            root, parent, count, children = c.c_ulong(), c.c_ulong(), c.c_uint(), c.POINTER(c.c_ulong)()
            if not self.x.XQueryTree(self.display, window, c.byref(root), c.byref(parent), c.byref(children), c.byref(count)):
                raise ValueError('desktop inventory unavailable')
            try:
                if count.value > 512:
                    raise ValueError('desktop inventory bound exceeded')
                queue.extend((children[i], depth + 1) for i in range(count.value))
            finally:
                if children: self.x.XFree(children)
        return found

    def pid(self, window):
        kind, fmt, count, remaining, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong(), c.POINTER(c.c_ubyte)()
        status = self.x.XGetWindowProperty(self.display, window, self.pid_atom, 0, 1, False,
            self.cardinal, c.byref(kind), c.byref(fmt), c.byref(count), c.byref(remaining), c.byref(data))
        try:
            if status or kind.value != self.cardinal or fmt.value != 32 or count.value != 1 or remaining.value or not data:
                return None
            value = c.cast(data, c.POINTER(c.c_ulong))[0]
            return value if 0 < value < 2**31 else None
        finally:
            if data: self.x.XFree(data)

    def request_close(self, window, pid, current):
        # Recheck PID/protocol/process while the server excludes window reuse.
        self.x.XGrabServer(self.display)
        try:
            if self.pid(window) != pid or not current(): return False
            protocols, count = c.POINTER(c.c_ulong)(), c.c_int()
            if not self.x.XGetWMProtocols(self.display, window, c.byref(protocols), c.byref(count)): return False
            try:
                if not 0 <= count.value <= 128 or self.delete not in [protocols[i] for i in range(count.value)]: return False
            finally:
                if protocols: self.x.XFree(protocols)
            event = Event(); event.client.type = 33; event.client.display = self.display
            event.client.window = window; event.client.message_type = self.protocols; event.client.format = 32
            event.client.data.longs[0] = self.delete; event.client.data.longs[1] = 0
            return bool(self.x.XSendEvent(self.display, window, False, 0, c.byref(event)))
        finally:
            self.x.XUngrabServer(self.display); self.x.XFlush(self.display)


def request_exit(binding, prefix, observation, desktop, processes):
    selected = {}
    for process in processes:
        if len(selected) >= 32: raise ValueError('selected process bound exceeded')
        if observation.selected_game_running(binding, prefix, [process]) is True:
            try: selected[process.pid] = (process, process.create_time())
            except (OSError, observation.psutil.Error): continue
    requested = False
    for window in desktop.windows():
        pid = desktop.pid(window)
        if pid not in selected: continue
        process, created = selected[pid]
        def current():
            try:
                return process.create_time() == created and observation.selected_game_running(binding, prefix, [process]) is True
            except (OSError, observation.psutil.Error): return False
        requested = desktop.request_close(window, pid, current) or requested
    return requested


def main():
    if sys.argv[1:] or os.geteuid() == 0: raise ValueError('session user required')
    observation, replay = sibling('dpad_instant_observation'), sibling('dpad_instant_replay')
    binding, _ = observation.installation.session_binding()
    observation.installation.session_launch_uri(binding)
    prefix = observation.installation.session_prefix()
    environment = replay.read(Path('/run/user') / str(os.geteuid()))
    desktop = X11(environment['DISPLAY'])
    try: requested = request_exit(binding, prefix, observation, desktop, observation.psutil.process_iter())
    finally: desktop.close()
    print(json.dumps({'schema': 1, 'exitRequested': requested, 'cloudSyncConfirmed': False}))


if __name__ == '__main__':
    try: main()
    except Exception:
        print('Selected game normal exit unavailable', file=sys.stderr); sys.exit(1)
