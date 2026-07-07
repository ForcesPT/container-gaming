// Validator for the MAIN-branch evdev interposer: opens /dev/input/event1000
// (the path fake-libudev advertises + the new interposer intercepts), reads
// struct input_event frames, prints type/code/value. The interposer translates
// the js_events from the Selkies gamepad socket into evdev input_events.
//   gcc -O2 -o /tmp/evclient /tmp/evclient.c
//   LD_PRELOAD=.../selkies_joystick_interposer.so /tmp/evclient /dev/input/event1000
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <time.h>

struct input_event {
    long sec;     // __kernel_long_t
    long usec;
    uint16_t type;
    uint16_t code;
    int32_t value;
};

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/dev/input/event1000";
    fprintf(stderr, "[evclient] open(%s) ...\n", path);
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    fprintf(stderr, "[evclient] open() -> fd=%d (interposer connected + read config)\n", fd);
    struct input_event ev;
    int got = 0, n = 0;
    while (n < 16) {
        ssize_t r = read(fd, &ev, sizeof(ev));
        if (r < 0) { perror("read"); break; }
        if (r == 0) { fprintf(stderr, "[evclient] EOF\n"); break; }
        if (r != (ssize_t)sizeof(ev)) { fprintf(stderr, "[evclient] short read %zd\n", r); break; }
        if (n < 3) {
            unsigned char *b = (unsigned char *)&ev;
            fprintf(stderr, "[evclient] raw: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
                b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15],b[16],b[17],b[18],b[19],b[20],b[21],b[22],b[23]);
        }
        const char *t = (ev.type == 0x01) ? "EV_KEY" : (ev.type == 0x03) ? "EV_ABS" : (ev.type == 0x00) ? "EV_SYN" : "?";
        fprintf(stderr, "[evclient] input_event %s code=%u value=%d (sec=%ld usec=%ld)\n",
                t, ev.code, ev.value, ev.sec, ev.usec);
        if (ev.type != 0x00) got++;
        n++;
    }
    fprintf(stderr, "[evclient] decoded %d non-SYN events — %s\n", got,
            got ? "OK: evdev path works" : "FAIL: no events");
    close(fd);
    return got ? 0 : 1;
}