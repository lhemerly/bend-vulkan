#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>

static void string(const char* s) {
  putchar('"');
  for (const unsigned char* p=(const unsigned char*)s; *p; p++) {
    if (*p=='"' || *p=='\\') printf("\\%c", *p);
    else if (*p<32) printf("\\u%04x", *p);
    else putchar(*p);
  }
  putchar('"');
}

int main(void) {
  VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion=VK_API_VERSION_1_2};
  VkInstanceCreateInfo create={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&app};
  VkInstance instance;
  if (vkCreateInstance(&create, NULL, &instance)!=VK_SUCCESS) {
    fputs("Vulkan 1.2 loader/device unavailable\n", stderr); return 1;
  }
  uint32_t count=0;
  if (vkEnumeratePhysicalDevices(instance, &count, NULL)!=VK_SUCCESS || count>64) return 1;
  VkPhysicalDevice devices[64];
  if (count && vkEnumeratePhysicalDevices(instance, &count, devices)!=VK_SUCCESS) return 1;
  putchar('[');
  for (uint32_t i=0; i<count; i++) {
    VkPhysicalDeviceProperties p; vkGetPhysicalDeviceProperties(devices[i], &p);
    VkPhysicalDeviceVulkan12Features f12={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceFeatures2 f2={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext=&f12};
    vkGetPhysicalDeviceFeatures2(devices[i], &f2);
    if (i) putchar(',');
    printf("{\"index\":%u,\"type\":%u,\"name\":", i, p.deviceType); string(p.deviceName);
    printf(",\"shaderInt64\":%s,\"deviceScopeMemoryModel\":%s,\"maxHeapBytes\":%u}",
      f2.features.shaderInt64?"true":"false",
      f12.vulkanMemoryModel && f12.vulkanMemoryModelDeviceScope?"true":"false", p.limits.maxStorageBufferRange);
  }
  puts("]"); vkDestroyInstance(instance, NULL); return 0;
}
