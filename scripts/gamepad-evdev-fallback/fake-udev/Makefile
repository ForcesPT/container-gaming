TARGET_SO = libudev.so.1
TARGET_BASENAME = libudev.so
LIB_VERSION ?= 1.0.0-fake
FULL_TARGET = $(TARGET_BASENAME).$(LIB_VERSION)
CC = gcc
CFLAGS = -Wall -Wextra -fPIC -DPIC -O2 -g
LDFLAGS = -shared
LDFLAGS += -Wl,--version-script=libudev.sym
LDFLAGS += -Wl,-soname,$(TARGET_SO)
SOURCES = fake-libudev-core.c
OBJECTS = $(SOURCES:.c=.o)

# 32-bit build variables.
# NOTE: the OUTPUT filename is libudev_x86.so.1 only to avoid colliding with the
# x86_64 build in this same dir — but the embedded SONAME MUST be libudev.so.1.
# Steam's main binary is 32-bit (ubuntu12_32/steam) and resolves gamepad
# discovery via dlopen("libudev.so.1") + dlsym (SDL3's SDL_udev.c). dlopen
# matches by SONAME, not filename: if the fake's soname were libudev_x86.so.1,
# dlopen would skip it and load the REAL libudev.so.1 shipped by the steam
# runtime -> real enumeration over /sys (the fake /dev/input nodes have no
# /sys backing) + no udev daemon -> zero devices -> no gamepad (the bug this
# fixes). With soname=libudev.so.1, the LD_PRELOAD'd fake satisfies the soname
# so dlopen reuses the already-loaded fake -> fake enumeration -> 8 fake nodes.
TARGET_SO_32 = libudev_x86.so.1
SONAME_32 = libudev.so.1
TARGET_BASENAME_32 = libudev_x86.so
FULL_TARGET_32 = $(TARGET_BASENAME_32).$(LIB_VERSION)
CFLAGS_32 = $(CFLAGS) -m32
LDFLAGS_32 = -shared -Wl,--version-script=libudev.sym -m32
LDFLAGS_32 += -Wl,-soname,$(SONAME_32)
OBJECTS_32 = $(SOURCES:.c=.x86.o)

all: $(FULL_TARGET) $(TARGET_SO) $(TARGET_BASENAME)

all32: $(FULL_TARGET_32) $(TARGET_SO_32) $(TARGET_BASENAME_32)

$(FULL_TARGET): $(OBJECTS) libudev.h libudev.sym
	$(CC) $(LDFLAGS) -o $@ $(OBJECTS)
	@echo "Built $@"
$(TARGET_SO): $(FULL_TARGET)
	@echo "Creating SONAME symlink $(TARGET_SO) -> $(FULL_TARGET)"
	@ln -sf $(FULL_TARGET) $(TARGET_SO)
$(TARGET_BASENAME): $(TARGET_SO)
	@echo "Creating symlink $(TARGET_BASENAME) -> $(TARGET_SO)"
	@ln -sf $(TARGET_SO) $(TARGET_BASENAME)

# 32-bit build targets
$(FULL_TARGET_32): $(OBJECTS_32) libudev.h libudev.sym
	$(CC) $(LDFLAGS_32) -o $@ $(OBJECTS_32)
	@echo "Built $@"

$(TARGET_SO_32): $(FULL_TARGET_32)
	@echo "Creating SONAME symlink $(TARGET_SO_32) -> $(FULL_TARGET_32)"
	@ln -sf $(FULL_TARGET_32) $(TARGET_SO_32)

$(TARGET_BASENAME_32): $(TARGET_SO_32)
	@echo "Creating symlink $(TARGET_BASENAME_32) -> $(TARGET_SO_32)"
	@ln -sf $(TARGET_SO_32) $(TARGET_BASENAME_32)

%.o: %.c libudev.h
	$(CC) $(CFLAGS) -c -o $@ $<

%.x86.o: %.c libudev.h
	$(CC) $(CFLAGS_32) -c -o $@ $<

clean:
	rm -f $(OBJECTS) $(OBJECTS_32) $(FULL_TARGET) $(TARGET_SO) $(TARGET_BASENAME) $(FULL_TARGET_32) $(TARGET_SO_32) $(TARGET_BASENAME_32) core.* *.core

.PHONY: all all32 clean
