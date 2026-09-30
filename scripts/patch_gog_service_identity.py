#!/usr/bin/python3
"""Extend the pinned Epic SCM compatibility patch to the exact official Galaxy service."""
from pathlib import Path
import sys

source = Path(sys.argv[1])
text = source.read_text()
start = text.index('static BOOL is_epic_eos_system_service(')
end = text.index('\nstatic void *epic_token_information', start)
old = text[start:end]
if old.count('EpicOnlineServicesHost.exe') != 2 or 'GalaxyClientService' in old:
    raise SystemExit('Pinned service identity predicate mismatch')
replacement = r'''static BOOL is_epic_eos_system_service(const struct service_entry *service)
{
    const WCHAR *binary = service->config.lpBinaryPathName;
    if (!binary || service->config.dwServiceType != SERVICE_WIN32_OWN_PROCESS
        || !service->config.lpDisplayName || !service->config.lpServiceStartName
        || wcsicmp(service->config.lpServiceStartName, L"LocalSystem")) return FALSE;

    return (!wcscmp(service->name, L"EpicOnlineServices")
            && !wcscmp(service->config.lpDisplayName, L"Epic Online Services")
            && (!wcsicmp(binary, L"C:\\Program Files (x86)\\Epic Games\\Epic Online Services\\service\\EpicOnlineServicesHost.exe")
                || !wcsicmp(binary, L"\"C:\\Program Files (x86)\\Epic Games\\Epic Online Services\\service\\EpicOnlineServicesHost.exe\"")))
        || (!wcscmp(service->name, L"GalaxyClientService")
            && !wcscmp(service->config.lpDisplayName, L"GalaxyClientService")
            && (!wcsicmp(binary, L"\"\\\\?\\C:\\Program Files\\GOG Galaxy\\GalaxyClientService.exe\"")
                || !wcsicmp(binary, L"\"C:\\Program Files\\GOG Galaxy\\GalaxyClientService.exe\"")));
}
'''
source.write_text(text[:start] + replacement + text[end:])
text = source.read_text()
marker = '    epic_system_service = is_epic_eos_system_service(service_entry);'
if text.count(marker) != 1:
    raise SystemExit('Pinned SCM process creation mismatch')
text = text.replace(marker, marker + r'''
    if (!wcscmp(service_entry->name, L"GalaxyClientService")
        && GetEnvironmentVariableA("DPAD_STORE_SERVICE_DIAGNOSTICS", NULL, 0))
        WINE_ERR("DPAD_LOCAL_GOG_SCM_MATCH=%d\n", epic_system_service);
''')
source.write_text(text)
server = Path(sys.argv[2])
text = server.read_text()
old = 'privs, req->priv_count, dacl, NULL, req->primary_group, req->impersonation_level, 0 );'
if text.count(old) != 1:
    raise SystemExit('Pinned NtCreateToken elevation initialization mismatch')
# NtCreateToken currently records elevation type 0 even for LocalSystem.
# Windows LocalSystem services need an elevated primary token. Ordinary user
# tokens keep their existing behavior; this changes no Unix account privileges.
new = '''privs, req->priv_count, dacl, NULL, req->primary_group, req->impersonation_level,
                          req->primary && equal_sid( user, &local_system_sid ) ? TokenElevationTypeFull : 0 );'''
server.write_text(text.replace(old, new))
