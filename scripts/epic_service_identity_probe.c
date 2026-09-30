/* Disposable, account-free Wine SCM identity fixture. Never an Epic binary. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static SERVICE_STATUS_HANDLE service_handle;
static void WINAPI control(DWORD code) { (void)code; }
static void state(DWORD value)
{
    SERVICE_STATUS status = {0};
    status.dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    status.dwCurrentState = value;
    SetServiceStatus(service_handle, &status);
}
static void WINAPI service_main(DWORD argc, WCHAR **argv)
{
    HANDLE token;
    DWORD size = 0;
    TOKEN_USER *user;
    WCHAR report[MAX_PATH];
    FILE *output;
    if (argc != 2) return;
    service_handle = RegisterServiceCtrlHandlerW(argv[0], control);
    if (!service_handle) return;
    state(SERVICE_RUNNING);
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        GetTokenInformation(token, TokenUser, NULL, 0, &size);
        user = HeapAlloc(GetProcessHeap(), 0, size);
        if (user && GetTokenInformation(token, TokenUser, user, size, &size)) {
            swprintf(report, MAX_PATH, L"C:\\eos-identity-%ls.json", argv[1]);
            output = _wfopen(report, L"w");
            if (output) {
                fprintf(output, "{\"case\":%ls,\"system_user\":%s}\n", argv[1],
                    IsWellKnownSid(user->User.Sid, WinLocalSystemSid) ? "true" : "false");
                fclose(output);
            }
        }
        if (user) HeapFree(GetProcessHeap(), 0, user);
        CloseHandle(token);
    }
    state(SERVICE_STOPPED);
}
int main(int argc, char **argv)
{
    const WCHAR epic_path[] = L"C:\\Program Files (x86)\\Epic Games\\Epic Online Services\\service\\EpicOnlineServicesHost.exe";
    const WCHAR other_path[] = L"C:\\DpadEosOther.exe";
    WCHAR executable[MAX_PATH], command[MAX_PATH+4], number[8], report[MAX_PATH];
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    SC_HANDLE manager, service;
    SERVICE_STATUS status;
    FILE *output;
    char line[256];
    DWORD attempt, index;
    if (!ntdll || !GetProcAddress(ntdll, "wine_get_version")) return 2;
    if (argc == 1) {
        SERVICE_TABLE_ENTRYW table[] = {{L"EpicOnlineServices", service_main}, {NULL, NULL}};
        return StartServiceCtrlDispatcherW(table) ? 0 : 3;
    }
    if (argc != 2 || strcmp(argv[1], "--compare")) return 2;
    if (!GetEnvironmentVariableW(L"DPAD_ACCOUNT_FREE_SERVICE_FIXTURE", number, 8) || wcscmp(number,L"1")) return 2;
    if (!GetModuleFileNameW(NULL, executable, MAX_PATH)) return 4;
    CreateDirectoryW(L"C:\\Program Files (x86)\\Epic Games", NULL);
    CreateDirectoryW(L"C:\\Program Files (x86)\\Epic Games\\Epic Online Services", NULL);
    CreateDirectoryW(L"C:\\Program Files (x86)\\Epic Games\\Epic Online Services\\service", NULL);
    /* TRUE prevents overwriting an installed official binary. */
    if (!CopyFileW(executable, epic_path, TRUE) || !CopyFileW(executable, other_path, TRUE)) return 5;
    manager = OpenSCManagerW(NULL,NULL,SC_MANAGER_ALL_ACCESS);
    if (!manager) return 6;
    for (index=0; index<6; ++index) {
        const WCHAR *name = index == 1 ? L"DpadPlayEosControl" : L"EpicOnlineServices";
        const WCHAR *display = index == 2 ? L"DpadPlay EOS Control" : L"Epic Online Services";
        const WCHAR *account = index == 4 ? L"NT AUTHORITY\\LocalService" : L"LocalSystem";
        swprintf(command, MAX_PATH+4, L"\"%ls\"", index == 3 ? other_path : epic_path);
        swprintf(number, 8, L"%lu", index);
        swprintf(report, MAX_PATH, L"C:\\eos-identity-%lu.json", index);
        service = CreateServiceW(manager,name,display,SERVICE_ALL_ACCESS,
            SERVICE_WIN32_OWN_PROCESS | (index==5 ? SERVICE_INTERACTIVE_PROCESS : 0),
            SERVICE_DEMAND_START,SERVICE_ERROR_NORMAL,command,NULL,NULL,NULL,account,NULL);
        if (!service) { fprintf(stderr,"fixture_create_error=%lu case=%lu\n",GetLastError(),index); CloseServiceHandle(manager); return 7; }
        {
            const WCHAR *args[] = {number};
            if (!StartServiceW(service,1,args)) { fprintf(stderr,"fixture_start_error=%lu case=%lu\n",GetLastError(),index); DeleteService(service); CloseServiceHandle(service); CloseServiceHandle(manager); return 8; }
        }
        for (attempt=0; attempt<40; ++attempt) {
            if (QueryServiceStatus(service,&status) && status.dwCurrentState==SERVICE_STOPPED) break;
            Sleep(250);
        }
        if (attempt==40) ControlService(service,SERVICE_CONTROL_STOP,&status);
        DeleteService(service); CloseServiceHandle(service);
        output = _wfopen(report,L"r");
        if (!output) { CloseServiceHandle(manager); return 9; }
        while (fgets(line,sizeof(line),output)) fputs(line,stdout);
        fclose(output);
        Sleep(500);
    }
    CloseServiceHandle(manager);
    return 0;
}
