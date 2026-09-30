/* Account-free behavior probe for the exact Galaxy renderer compatibility gate. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void)
{
    WCHAR value[256];
    const char *crt;
    int win32, crt_ok, deletion;
    FILE *receipt;
    SetEnvironmentVariableW(L"QTWEBENGINE_CHROMIUM_FLAGS", L"--disable-renderer-accessibility");
    GetEnvironmentVariableW(L"QTWEBENGINE_CHROMIUM_FLAGS", value, 256);
    win32 = wcsstr(value, L"--disable-gpu") != NULL;
    _putenv("QTWEBENGINE_CHROMIUM_FLAGS=--disable-renderer-accessibility");
    crt = getenv("QTWEBENGINE_CHROMIUM_FLAGS");
    crt_ok = crt && strstr(crt, "--disable-gpu") != NULL;
    SetEnvironmentVariableW(L"QTWEBENGINE_CHROMIUM_FLAGS", NULL);
    deletion = GetEnvironmentVariableW(L"QTWEBENGINE_CHROMIUM_FLAGS", value, 256) == 0;
    receipt = fopen("C:\\dpad-gog-environment-probe.txt", "w");
    if (!receipt) return 2;
    fprintf(receipt, "win32=%d crt=%d deletion=%d\n", win32, crt_ok, deletion);
    fclose(receipt);
    return 0;
}
