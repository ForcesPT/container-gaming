// Minimal libudev enumeration test — mimics how SDL3 discovers evdev gamepads.
// Links against libudev; under LD_PRELOAD=fake-libudev it should "see" the 4
// virtual XBox 360 pads the fake library advertises.
#include <stdio.h>
#include <libudev.h>
int main(void) {
    struct udev *u = udev_new();
    if (!u) { fprintf(stderr, "udev_new FAILED\n"); return 1; }
    struct udev_enumerate *e = udev_enumerate_new(u);
    udev_enumerate_add_match_subsystem(e, "input");
    udev_enumerate_scan_devices(e);
    struct udev_list_entry *le = udev_enumerate_get_list_entry(e);
    int n = 0;
    for (; le != NULL; le = udev_list_entry_get_next(le)) {
        const char *syspath = udev_list_entry_get_name(le);
        struct udev_device *d = udev_device_new_from_syspath(u, syspath);
        if (!d) continue;
        const char *devname = udev_device_get_devnode(d);
        const char *idjoy = udev_device_get_property_value(d, "ID_INPUT_JOYSTICK");
        const char *name = udev_device_get_sysattr_value(d, "name");
        if (devname && idjoy) {
            fprintf(stderr, "[udev] found device devname=%s name=%s ID_INPUT_JOYSTICK=%s\n",
                    devname, name ? name : "?", idjoy);
            n++;
        }
        udev_device_unref(d);
    }
    udev_enumerate_unref(e);
    udev_unref(u);
    fprintf(stderr, "[udev] discovered %d joystick devices — %s\n",
            n, n ? "OK: fake-libudev works" : "FAIL: no gamepads seen");
    return n ? 0 : 1;
}