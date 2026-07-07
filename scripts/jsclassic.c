// Validator that mimics SDL3's classic-joystick discovery path on /dev/input/js0
// (SDL_HINT_JOYSTICK_LINUX_CLASSIC): open, then probe JSIOCGVERSION/JSIOCGNAME/
// JSIOCGBUTTONS/JSIOCGAXES/JSIOCGBTNMAP/JSIOCGAXMAP, then read js_event structs.
// Run under the v1.6.2 interposer LD_PRELOAD + a feeder on /tmp/selkies_js0.sock.
//   gcc -O2 -o /tmp/jsclassic /tmp/jsclassic.c
//   LD_PRELOAD=.../selkies_joystick_interposer.so /tmp/jsclassic
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <errno.h>
#include <linux/joystick.h>

int main(void) {
    const char *path = "/dev/input/js0";
    fprintf(stderr, "[classic] open(%s)\n", path);
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0) { perror("open"); return 1; }
    fprintf(stderr, "[classic] open -> fd=%d\n", fd);

    unsigned int version = 0;
    char name[128] = {0};
    unsigned char nbtn = 0, nax = 0;
    uint16_t btnmap[512] = {0};
    uint8_t axmap[64] = {0};
    if (ioctl(fd, JSIOCGVERSION, &version) < 0) perror("JSIOCGVERSION");
    if (ioctl(fd, JSIOCGNAME(sizeof(name)), name) < 0) perror("JSIOCGNAME");
    if (ioctl(fd, JSIOCGBUTTONS, &nbtn) < 0) perror("JSIOCGBUTTONS");
    if (ioctl(fd, JSIOCGAXES, &nax) < 0) perror("JSIOCGAXES");
    if (ioctl(fd, JSIOCGBTNMAP, btnmap) < 0) perror("JSIOCGBTNMAP");
    if (ioctl(fd, JSIOCGAXMAP, axmap) < 0) perror("JSIOCGAXMAP");
    fprintf(stderr, "[classic] version=0x%x name='%s' buttons=%d axes=%d\n",
            version, name, nbtn, nax);
    fprintf(stderr, "[classic] btnmap[0..4]=%u,%u,%u,%u,%u  axmap[0..3]=%u,%u,%u,%u\n",
            btnmap[0], btnmap[1], btnmap[2], btnmap[3], btnmap[4],
            axmap[0], axmap[1], axmap[2], axmap[3]);

    struct js_event ev;
    int got = 0, n = 0;
    while (n < 6) {
        ssize_t r = read(fd, &ev, sizeof(ev));
        if (r < 0) { if (errno == EAGAIN) { usleep(50000); n++; continue; } perror("read"); break; }
        if (r == 0) { fprintf(stderr, "[classic] EOF\n"); break; }
        if (r != (ssize_t)sizeof(ev)) { fprintf(stderr, "[classic] short %zd\n", r); break; }
        const char *t = (ev.type & 0x01) ? "BTN" : (ev.type & 0x02) ? "AXIS" : "?";
        fprintf(stderr, "[classic] js_event %s num=%u value=%d\n", t, ev.number, ev.value);
        got++; n++;
    }
    fprintf(stderr, "[classic] decoded %d events — %s\n", got,
            got ? "OK: SDL3 classic path works" : "FAIL");
    close(fd);
    return got ? 0 : 1;
}