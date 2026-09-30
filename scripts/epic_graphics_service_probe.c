/* Account-free diagnostic: compare D3D11/Vulkan in the user and service context.
 * No Epic account, installed client, or production prefix is used.
 */
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <d3d11.h>
#include <stdio.h>
#include <string.h>

typedef struct { char name[256]; DWORD version; } Extension;
typedef int (WINAPI *EnumerateExtensions)(const char *, DWORD *, Extension *);
static const WCHAR *service_name = L"DpadPlayLocalGraphicsProbe";
static SERVICE_STATUS_HANDLE service_handle;
static char report_path[MAX_PATH];

static void graphics(FILE *output, const char *context)
{
    ID3D11Device *device = NULL;
    ID3D11DeviceContext *device_context = NULL;
    D3D_FEATURE_LEVEL obtained;
    USEROBJECTFLAGS flags = {0};
    DWORD needed = 0, count = 0, i;
    Extension extensions[256];
    HMODULE vulkan;
    union { FARPROC address; EnumerateExtensions enumerate; } function;
    EnumerateExtensions enumerate;
    int result = -999, win32_surface = 0;
    HRESULT status;
    fprintf(output, "PROBE_CONTEXT_START %s\n", context); fflush(output);
    vulkan = LoadLibraryA("vulkan-1.dll");
    function.address = vulkan ? GetProcAddress(vulkan, "vkEnumerateInstanceExtensionProperties") : NULL;
    enumerate = function.enumerate;
    GetUserObjectInformationA(GetProcessWindowStation(), UOI_FLAGS, &flags, sizeof(flags), &needed);
    if (enumerate && !enumerate(NULL, &count, NULL) && count <= 256) {
        result = enumerate(NULL, &count, extensions);
        if (!result) for (i = 0; i < count; ++i)
            if (!strcmp(extensions[i].name, "VK_KHR_win32_surface")) win32_surface = 1;
    }
    fprintf(output, "PROBE_D3D11_START %s vulkan=%d win32_surface=%d\n", context, result, win32_surface); fflush(output);
    status = D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, 0, NULL, 0,
                             D3D11_SDK_VERSION, &device, &obtained, &device_context);
    fprintf(output, "{\"context\":\"%s\",\"interactive_station\":%s,\"vulkan_enumeration\":%d,\"win32_surface\":%s,\"d3d11_hresult\":\"0x%08lx\",\"d3d11_ok\":%s}\n",
            context, flags.dwFlags & WSF_VISIBLE ? "true" : "false", result,
            win32_surface ? "true" : "false", (unsigned long)status,
            SUCCEEDED(status) ? "true" : "false");
    fflush(output);
    if (device_context) ID3D11DeviceContext_Release(device_context);
    if (device) ID3D11Device_Release(device);
    if (vulkan) FreeLibrary(vulkan);
}

static void state(DWORD value)
{
    SERVICE_STATUS status = {0};
    status.dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    status.dwCurrentState = value;
    SetServiceStatus(service_handle, &status);
}

static void WINAPI control(DWORD code) { (void)code; }

static void WINAPI service_main(DWORD argc, WCHAR **argv)
{
    FILE *output;
    (void)argc; (void)argv;
    service_handle = RegisterServiceCtrlHandlerW(service_name, control);
    if (!service_handle) return;
    state(SERVICE_RUNNING);
    output = fopen(report_path, "w");
    if (output) { graphics(output, "service"); fclose(output); }
    state(SERVICE_STOPPED);
}

int main(int argc, char **argv)
{
    WCHAR executable[MAX_PATH], command[2 * MAX_PATH + 40], report[MAX_PATH];
    SC_HANDLE manager, service;
    SERVICE_STATUS status;
    FILE *output;
    unsigned int attempt;
    char line[1024];
    char user_report[MAX_PATH + 6];
    int epic_target = argc == 4 && !strcmp(argv[3], "--epic-target");
    const WCHAR epic_path[] = L"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesUpdater.exe";
    if (argc == 1 && GetModuleFileNameW(NULL, executable, MAX_PATH) && !_wcsicmp(executable, epic_path)) {
        SERVICE_TABLE_ENTRYW table[] = {{L"EpicGamesUpdater", service_main}, {NULL, NULL}};
        service_name = L"EpicGamesUpdater";
        strcpy(report_path, "C:\\dpad-graphics.json");
        return StartServiceCtrlDispatcherW(table) ? 0 : 3;
    }
    if ((argc != 3 && argc != 4) || (strcmp(argv[1], "--compare") && strcmp(argv[1], "--service"))) return 2;
    if (argc == 4 && strcmp(argv[3], "--interactive") && !epic_target) return 2;
    if (strlen(argv[2]) >= sizeof(report_path)) return 2;
    strcpy(report_path, argv[2]);
    if (!strcmp(argv[1], "--service")) {
        SERVICE_TABLE_ENTRYW table[] = {{(WCHAR *)service_name, service_main}, {NULL, NULL}};
        return StartServiceCtrlDispatcherW(table) ? 0 : 3;
    }
    snprintf(user_report, sizeof(user_report), "%s.user", report_path);
    output = fopen(user_report, "w");
    if (!output) return 9;
    graphics(output, "user");
    fclose(output);
    if (!GetModuleFileNameW(NULL, executable, MAX_PATH)) return 4;
    MultiByteToWideChar(CP_UTF8, 0, report_path, -1, report, MAX_PATH);
    swprintf(command, sizeof(command) / sizeof(command[0]), L"\"%ls\" --service \"%ls\"", executable, report);
    if (epic_target) {
        /* Fake graphics executable only, in a fresh account-free test prefix. */
        CreateDirectoryW(L"C:\\Program Files\\Epic Games", NULL);
        CreateDirectoryW(L"C:\\Program Files\\Epic Games\\Launcher", NULL);
        CreateDirectoryW(L"C:\\Program Files\\Epic Games\\Launcher\\Portal", NULL);
        CreateDirectoryW(L"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries", NULL);
        CreateDirectoryW(L"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64", NULL);
        if (!CopyFileW(executable, epic_path, TRUE)) return 10;
        service_name = L"EpicGamesUpdater";
        swprintf(command, sizeof(command) / sizeof(command[0]), L"\"%ls\"", epic_path);
    }
    manager = OpenSCManagerW(NULL, NULL, SC_MANAGER_ALL_ACCESS);
    if (!manager) return 5;
    service = CreateServiceW(manager, service_name, epic_target ? L"Epic Games Updater" : service_name, SERVICE_ALL_ACCESS,
                            SERVICE_WIN32_OWN_PROCESS | (argc == 4 && !epic_target ? SERVICE_INTERACTIVE_PROCESS : 0), SERVICE_DEMAND_START,
                            SERVICE_ERROR_NORMAL, command, NULL, NULL, NULL, NULL, NULL);
    if (!service) { CloseServiceHandle(manager); return 6; }
    if (!StartServiceW(service, 0, NULL)) {
        fprintf(stderr, "probe_service_start_error=%lu\n", GetLastError());
        DeleteService(service); CloseServiceHandle(service); CloseServiceHandle(manager); return 7;
    }
    for (attempt = 0; attempt < 30; ++attempt) {
        if (QueryServiceStatus(service, &status) && status.dwCurrentState == SERVICE_STOPPED) break;
        Sleep(500);
    }
    if (attempt == 30) ControlService(service, SERVICE_CONTROL_STOP, &status);
    DeleteService(service); CloseServiceHandle(service); CloseServiceHandle(manager);
    output = fopen(report_path, "r");
    if (!output) { fprintf(stderr, "probe_service_report_missing\n"); return 8; }
    while (fgets(line, sizeof(line), output)) fputs(line, stdout);
    fclose(output);
    return 0;
}
