/* Test-only ICD proxy. Remove one capability from Mesa to reproduce the
 * noninteractive Wine service path. Never install this into a gaming image.
 */
#define _GNU_SOURCE
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

static void *driver;
static PFN_vkGetInstanceProcAddr get_instance;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static void load_driver(void)
{
    driver = dlopen("libvulkan_lvp.so", RTLD_NOW | RTLD_LOCAL | RTLD_DEEPBIND);
    if (driver) get_instance = (PFN_vkGetInstanceProcAddr)dlsym(driver, "vk_icdGetInstanceProcAddr");
}

static VkResult enumerate(const char *layer, uint32_t *count, VkExtensionProperties *properties)
{
    PFN_vkEnumerateInstanceExtensionProperties next = (PFN_vkEnumerateInstanceExtensionProperties)get_instance(NULL, "vkEnumerateInstanceExtensionProperties");
    VkExtensionProperties *available;
    uint32_t total = 0, filtered = 0, i, capacity = properties ? *count : 0;
    VkResult result = next(layer, &total, NULL);
    if (result != VK_SUCCESS) return result;
    available = calloc(total, sizeof(*available));
    if (!available) return VK_ERROR_OUT_OF_HOST_MEMORY;
    result = next(layer, &total, available);
    if (result == VK_SUCCESS) {
        for (i = 0; i < total; ++i) {
            if (!strcmp(available[i].extensionName, "VK_EXT_headless_surface")) continue;
            if (properties && filtered < capacity) properties[filtered] = available[i];
            ++filtered;
        }
        *count = properties && capacity < filtered ? capacity : filtered;
        if (properties && capacity < filtered) result = VK_INCOMPLETE;
    }
    free(available);
    return result;
}

static VkResult create(const VkInstanceCreateInfo *info, const VkAllocationCallbacks *allocator, VkInstance *instance)
{
    uint32_t i;
    PFN_vkCreateInstance next = (PFN_vkCreateInstance)get_instance(NULL, "vkCreateInstance");
    for (i = 0; i < info->enabledExtensionCount; ++i)
        if (!strcmp(info->ppEnabledExtensionNames[i], "VK_EXT_headless_surface"))
            return VK_ERROR_EXTENSION_NOT_PRESENT;
    return next(info, allocator, instance);
}

VKAPI_ATTR VkResult VKAPI_CALL vk_icdNegotiateLoaderICDInterfaceVersion(uint32_t *version)
{
    typedef VkResult (*Negotiate)(uint32_t *);
    Negotiate next;
    pthread_once(&once, load_driver);
    if (!driver) return VK_ERROR_INITIALIZATION_FAILED;
    next = (Negotiate)dlsym(driver, "vk_icdNegotiateLoaderICDInterfaceVersion");
    return next ? next(version) : VK_ERROR_INITIALIZATION_FAILED;
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vk_icdGetInstanceProcAddr(VkInstance instance, const char *name)
{
    pthread_once(&once, load_driver);
    if (!get_instance) return NULL;
    if (!strcmp(name, "vkCreateInstance")) return (PFN_vkVoidFunction)create;
    if (!strcmp(name, "vkEnumerateInstanceExtensionProperties")) return (PFN_vkVoidFunction)enumerate;
    return get_instance(instance, name);
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vk_icdGetPhysicalDeviceProcAddr(VkInstance instance, const char *name)
{
    PFN_vkGetInstanceProcAddr next;
    pthread_once(&once, load_driver);
    if (!driver) return NULL;
    next = (PFN_vkGetInstanceProcAddr)dlsym(driver, "vk_icdGetPhysicalDeviceProcAddr");
    return next ? next(instance, name) : NULL;
}
