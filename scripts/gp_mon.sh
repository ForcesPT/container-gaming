#!/usr/bin/env bash
# Comprehensive gamepad monitor: the moment Selkies' gamepad socket appears
# (user pressed a controller button), it:
#   1. runs the 32-bit SDL3 IsGamepad test (i386 interposer path - the one Steam uses)
#   2. waits, then checks whether any process now HOLDS /dev/input/js0 open
#      (Steam's SDL3 opening the gamepad to read events = the real success signal)
#   3. dumps new interposer log lines (full ioctl sequence)
LOG=/tmp/gp_mon.log
echo "[gp_mon] started $(date)" > "$LOG"
SDL32_DIR=/home/dpad/.steam/debian-installation/ubuntu12_32
INTERPOSER32=/usr/lib/i386-linux-gnu/selkies_joystick_interposer.so
MAPPING='0000d60653656c6b69657320436f6e00,Selkies Controller,a:b0,b:b1,x:b2,y:b3,back:b6,guide:b8,start:b7,leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,'

fired=0
while [ "$fired" -lt 1 ]; do
    if [ -S /tmp/selkies_js0.sock ]; then
        echo "[gp_mon] socket appeared at $(date +%s.%N)" >> "$LOG"
        opens_before=$(wc -l < /tmp/selkies_js.log 2>/dev/null || echo 0)

        # 1. 32-bit SDL3 test (i386 interposer - what Steam's 32-bit binary uses)
        echo "[gp_mon] === 32-bit SDL3 test (i386 interposer) ===" >> "$LOG"
        su -s /bin/bash dpad -c "
            export LD_PRELOAD='$INTERPOSER32'
            export SDL_JOYSTICK_LINUX_CLASSIC=1
            export SDL_JOYSTICK_DISABLE_UDEV=1
            export SDL_JOYSTICK_DEVICE=/dev/input/js0
            export SDL_GAMECONTROLLERCONFIG='$MAPPING'
            export LD_LIBRARY_PATH='$SDL32_DIR:\$LD_LIBRARY_PATH'
            /tmp/sdl3_guid_test32
        " >> "$LOG" 2>&1
        echo "[gp_mon] 32-bit test exit=$?" >> "$LOG"

        # 2. give Steam's SDL3 a moment to open the gamepad, then check who holds js0
        sleep 3
        echo "[gp_mon] === processes holding /dev/input/js0 open ===" >> "$LOG"
        found_open=0
        for p in /proc/[0-9]*; do
            for fd in $p/fd/*; do
                tgt=$(readlink "$fd" 2>/dev/null)
                if [ "$tgt" = /dev/input/js0 ]; then
                    pid=${p##*/}
                    cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-90)
                    echo "  PID $pid: $cmd" >> "$LOG"
                    found_open=1
                fi
            done
        done
        [ "$found_open" = 0 ] && echo "  (no process holds js0 open — Steam not reading events)" >> "$LOG"

        # 3. new interposer log lines (full ioctl sequence)
        echo "[gp_mon] === new interposer log lines (was $opens_before, now $(wc -l < /tmp/selkies_js.log)) ===" >> "$LOG"
        tail -n +$((opens_before+1)) /tmp/selkies_js.log 2>/dev/null >> "$LOG"

        echo "[gp_mon] === done $(date) ===" >> "$LOG"
        fired=$((fired+1))
    fi
    sleep 0.2
done