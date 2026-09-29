/* Local-only probe for the named EC key APIs used by Epic's DPoP flow. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <ncrypt.h>
#include <stdio.h>
#include <string.h>

static int fail(const char *step, SECURITY_STATUS status)
{
    fprintf(stderr, "%s failed: 0x%08lx\n", step, (unsigned long)status);
    return 1;
}

int main(int argc, char **argv)
{
    NCRYPT_PROV_HANDLE provider = 0;
    NCRYPT_KEY_HANDLE key = 0;
    const WCHAR name[] = L"DpadPlay-local-DPoP-probe";
    BYTE hash[32];
    BYTE public_blob[256];
    BYTE signature[256];
    DWORD public_size = 0, signature_size = 0;
    SECURITY_STATUS status;
    int create;
    unsigned int i;

    if (argc != 2 || (strcmp(argv[1], "create") && strcmp(argv[1], "open")))
    {
        fprintf(stderr, "usage: ncrypt_persistence_probe.exe create|open\n");
        return 2;
    }
    create = !strcmp(argv[1], "create");
    memset(hash, 0x5a, sizeof(hash));

    status = NCryptOpenStorageProvider(&provider, MS_KEY_STORAGE_PROVIDER, 0);
    if (status) return fail("NCryptOpenStorageProvider", status);
    if (create)
    {
        status = NCryptCreatePersistedKey(provider, &key, NCRYPT_ECDSA_P256_ALGORITHM,
                                           name, 0, 0);
        if (status) return fail("NCryptCreatePersistedKey", status);
        status = NCryptFinalizeKey(key, 0);
        if (status) return fail("NCryptFinalizeKey", status);
    }
    else
    {
        status = NCryptOpenKey(provider, &key, name, 0, 0);
        if (status) return fail("NCryptOpenKey", status);
    }

    status = NCryptExportKey(key, 0, BCRYPT_ECCPUBLIC_BLOB, NULL, public_blob,
                             sizeof(public_blob), &public_size, 0);
    if (status) return fail("NCryptExportKey", status);
    if (!public_size || public_size > sizeof(public_blob))
    {
        fprintf(stderr, "invalid public blob size: %lu\n", (unsigned long)public_size);
        return 1;
    }

    status = NCryptSignHash(key, NULL, hash, sizeof(hash), signature,
                            sizeof(signature), &signature_size, 0);
    if (status) return fail("NCryptSignHash", status);
    if (!signature_size || signature_size > sizeof(signature))
    {
        fprintf(stderr, "invalid signature size: %lu\n", (unsigned long)signature_size);
        return 1;
    }

    printf("public=");
    for (i = 0; i < public_size; ++i) printf("%02x", public_blob[i]);
    printf("\nsignature_bytes=%lu\n", (unsigned long)signature_size);
    NCryptFreeObject(key);
    NCryptFreeObject(provider);
    return 0;
}
