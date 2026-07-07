// Decisive GUID + gamepad-recognition test using Steam's bundled SDL3.
// Opens /dev/input/js1 via the v1.6.2 interposer (LD_PRELOAD), asks SDL3 for
// the joystick's actual GUID + whether SDL_GAMECONTROLLERCONFIG makes SDL3
// treat it as a gamepad. Links against Steam's libSDL3.so.0 at runtime.
#define SDL_INIT_JOYSTICK 0x00000200u
#define SDL_INIT_GAMEPAD  0x00002000u
typedef struct { unsigned char data[16]; } SDL_GUID;
typedef int SDL_JoystickID;
// SDL3 ABI (verify against the lib):
extern unsigned char SDL_Init(unsigned int flags);
extern void SDL_Quit(void);
extern const char *SDL_GetError(void);
extern SDL_JoystickID *SDL_GetJoysticks(int *count);
extern SDL_GUID SDL_GetJoystickGUIDForID(SDL_JoystickID instance_id);
extern unsigned char SDL_IsGamepad(SDL_JoystickID instance_id);
extern const char *SDL_GetGamepadNameForID(SDL_JoystickID instance_id);
extern const char *SDL_GetJoystickNameForID(SDL_JoystickID instance_id);
extern int SDL_AddGamepadMapping(const char *mapping);
extern void SDL_GUIDToString(SDL_GUID guid, char *pszGUID, int cbGUID);
extern void SDL_free(void *mem);

#include <stdio.h>
#include <string.h>
#include <dlfcn.h>

int main(int argc, char **argv) {
    const char *mapping = "0000d60653656c6b69657320436f6e00,Selkies Controller,a:b0,b:b1,x:b2,y:b3,back:b6,guide:b8,start:b7,leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,";
    fprintf(stderr, "step: calling SDL_Init\n"); fflush(stderr);
    if (SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMEPAD) == 0) {
        fprintf(stderr, "SDL_Init FAILED: %s\n", SDL_GetError()); return 1;
    }
    fprintf(stderr, "step: SDL_Init OK, adding mapping\n"); fflush(stderr);
    int r = SDL_AddGamepadMapping(mapping);
    fprintf(stderr, "SDL_AddGamepadMapping -> %d (1=new, 0=updated, -1=err: %s)\n", r, SDL_GetError());

    fprintf(stderr, "step: SDL_GetJoysticks\n"); fflush(stderr);
    int count = 0;
    SDL_JoystickID *ids = SDL_GetJoysticks(&count);
    fprintf(stderr, "SDL_GetJoysticks: count=%d\n", count); fflush(stderr);
    if (!ids) { fprintf(stderr, "no joysticks: %s\n", SDL_GetError()); return 1; }
    for (int i = 0; i < count; i++) {
        SDL_GUID g = SDL_GetJoystickGUIDForID(ids[i]);
        char guidstr[33] = {0};
        SDL_GUIDToString(g, guidstr, sizeof(guidstr));
        const char *jname = SDL_GetJoystickNameForID(ids[i]);
        int ispad = SDL_IsGamepad(ids[i]);
        const char *gname = SDL_GetGamepadNameForID(ids[i]);
        fprintf(stderr, "  joystick[%d] id=%d name='%s' GUID=%s  IsGamepad=%d  gamepadName='%s'\n",
                i, ids[i], jname ? jname : "?", guidstr, ispad, gname ? gname : "(null)");
    }
    SDL_free(ids);
    SDL_Quit();
    return 0;
}