// Validator for the Selkies v1.6.2 joystick interposer. Calls open() directly
// (the syscall the interposer hooks), reads js_event structs from /dev/input/js0,
// prints them. Pair with a socket feeder at /tmp/selkies_js0.sock.
//   gcc -O2 -o /tmp/jsclient /tmp/jsclient.c
//   LD_PRELOAD=/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so /tmp/jsclient
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <stdint.h>

struct js_event {
    uint32_t time;
    int16_t value;
    uint8_t type;
    uint8_t number;
};

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/dev/input/js0";
    fprintf(stderr, "[client] open(%s) ... (LD_PRELOAD interposer will redirect)\n", path);
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    fprintf(stderr, "[client] open() -> fd=%d (interposer connected + read config)\n", fd);

    struct js_event ev;
    int n = 0, got = 0;
    while (n < 6) {
        ssize_t r = read(fd, &ev, sizeof(ev));
        if (r < 0) { perror("read"); break; }
        if (r == 0) { fprintf(stderr, "[client] EOF\n"); break; }
        if (r != (ssize_t)sizeof(ev)) {
            fprintf(stderr, "[client] short read %zd\n", r);
            break;
        }
        const char *t = (ev.type & 0x01) ? "BTN" : (ev.type & 0x02) ? "AXIS" : "?";
        fprintf(stderr, "[client] js_event %s num=%u value=%d (time=%u type=0x%02x)\n",
                t, ev.number, ev.value, ev.time, ev.type);
        got++; n++;
    }
    fprintf(stderr, "[client] decoded %d events — %s\n", got,
            got ? "OK: plumbing works" : "FAIL: no events");
    close(fd);
    return got ? 0 : 1;
}