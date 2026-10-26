/* Included in the host half of the pinned Bend runtime. The corpus is either
 * mapped directly when device-local host-visible memory exists, or copied via a
 * mapped staging buffer; ownership transfers at dispatch/fence bounds. */
#include <vulkan/vulkan.h>

#define VK_CHECK(call) do { VkResult rc_ = (call); if (rc_ != VK_SUCCESS) { \
  char message_[192]; snprintf(message_, sizeof message_, "Vulkan %s: %d", #call, rc_); \
  err_fail(message_); } } while (0)

static VkInstance vk_instance;
static VkPhysicalDevice vk_physical;
static VkPhysicalDeviceProperties vk_properties;
static VkDevice vk_device;
static VkQueue vk_queue;
static u32 vk_family;
static VkBuffer vk_buffer;
static VkDeviceMemory vk_memory;
static VkDeviceSize vk_bytes;
static VkBuffer vk_staging_buffer;
static VkDeviceMemory vk_staging_memory;
static void* vk_map;
static void* vk_staging_map;
static bool vk_coherent;
static bool vk_staged;
static VkDescriptorSetLayout vk_set_layout;
static VkDescriptorPool vk_pool;
static VkDescriptorSet vk_set;
static VkPipelineLayout vk_layout;
static VkShaderModule vk_shader;
static VkPipeline vk_pipeline;
static VkCommandPool vk_commands;
static VkCommandBuffer vk_command;
static VkFence vk_fence;
static u64 vk_dispatches;

static void vk_cleanup(void) {
  if (getenv("BEND_VULKAN_TRACE") && vk_physical)
    fprintf(stderr, "Vulkan device=%s memory=%s dispatches=%llu\n",
      vk_properties.deviceName, vk_staged ? "staged" : "host-visible",
      (unsigned long long)vk_dispatches);
  if (vk_device) {
    vkDeviceWaitIdle(vk_device);
    if (vk_fence) vkDestroyFence(vk_device, vk_fence, NULL);
    if (vk_commands) vkDestroyCommandPool(vk_device, vk_commands, NULL);
    if (vk_pipeline) vkDestroyPipeline(vk_device, vk_pipeline, NULL);
    if (vk_shader) vkDestroyShaderModule(vk_device, vk_shader, NULL);
    if (vk_layout) vkDestroyPipelineLayout(vk_device, vk_layout, NULL);
    if (vk_pool) vkDestroyDescriptorPool(vk_device, vk_pool, NULL);
    if (vk_set_layout) vkDestroyDescriptorSetLayout(vk_device, vk_set_layout, NULL);
    if (vk_staging_map) {
      vkUnmapMemory(vk_device, vk_staging_memory);
      if (vk_map == vk_staging_map) vk_map = NULL;
      vk_staging_map = NULL;
    }
    if (vk_staging_buffer) vkDestroyBuffer(vk_device, vk_staging_buffer, NULL);
    if (vk_staging_memory) vkFreeMemory(vk_device, vk_staging_memory, NULL);
    if (vk_map) vkUnmapMemory(vk_device, vk_memory);
    if (vk_buffer) vkDestroyBuffer(vk_device, vk_buffer, NULL);
    if (vk_memory) vkFreeMemory(vk_device, vk_memory, NULL);
    vkDestroyDevice(vk_device, NULL);
  }
  if (vk_instance) vkDestroyInstance(vk_instance, NULL);
}

static const char* gpu_probe(void) {
  if (vk_device) return NULL;
  VkApplicationInfo app = {.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,
    .pApplicationName="Bend Vulkan", .apiVersion=VK_API_VERSION_1_2};
  VkInstanceCreateInfo ici = {.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&app};
  if (vkCreateInstance(&ici, NULL, &vk_instance) != VK_SUCCESS) return "Vulkan 1.2 loader/device unavailable";
  atexit(vk_cleanup);
  u32 count = 0;
  VK_CHECK(vkEnumeratePhysicalDevices(vk_instance, &count, NULL));
  if (!count || count > 64) return "no supported Vulkan device inventory";
  VkPhysicalDevice devices[64];
  VK_CHECK(vkEnumeratePhysicalDevices(vk_instance, &count, devices));
  const char* selection = getenv("BEND_VULKAN_DEVICE");
  char* end = NULL;
  unsigned long index = selection ? strtoul(selection, &end, 10) : 0;
  if ((selection && (!*selection || *selection=='-' || *end)) || index >= count)
    return "invalid BEND_VULKAN_DEVICE index";
  vk_physical = devices[index];
  vkGetPhysicalDeviceProperties(vk_physical, &vk_properties);
  if (vk_properties.deviceType != VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU &&
      vk_properties.deviceType != VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU &&
      (!getenv("BEND_VULKAN_SOFTWARE") || strcmp(getenv("BEND_VULKAN_SOFTWARE"), "1")))
    return "software Vulkan requires --software / BEND_VULKAN_SOFTWARE=1";
  if (vk_properties.apiVersion < VK_API_VERSION_1_2 ||
      vk_properties.limits.maxComputeWorkGroupInvocations < CUBE_T ||
      vk_properties.limits.maxComputeWorkGroupSize[0] < CUBE_T ||
      vk_properties.limits.maxComputeSharedMemorySize < TG_HOLD * 8)
    return "Vulkan compute limits below Bend runtime requirements";
  VkPhysicalDeviceVulkan12Features f12 = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
  VkPhysicalDeviceFeatures2 f2 = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext=&f12};
  vkGetPhysicalDeviceFeatures2(vk_physical, &f2);
  if (!f2.features.shaderInt64 || !f12.vulkanMemoryModel || !f12.vulkanMemoryModelDeviceScope)
    return "Vulkan shaderInt64 and device-scope memory model required";
  u32 families = 0;
  vkGetPhysicalDeviceQueueFamilyProperties(vk_physical, &families, NULL);
  VkQueueFamilyProperties* properties = calloc(families, sizeof(*properties));
  if (!properties) return "Vulkan queue allocation failed";
  vkGetPhysicalDeviceQueueFamilyProperties(vk_physical, &families, properties);
  vk_family = UINT32_MAX;
  for (u32 i=0; i<families; i++) if (properties[i].queueCount && (properties[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) {
    vk_family=i; break;
  }
  free(properties);
  if (vk_family == UINT32_MAX) return "Vulkan compute queue unavailable";
  float priority=0.2f;
  VkDeviceQueueCreateInfo qci={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
    .queueFamilyIndex=vk_family, .queueCount=1, .pQueuePriorities=&priority};
  VkPhysicalDeviceFeatures enabled={.shaderInt64=VK_TRUE};
  VkPhysicalDeviceVulkan12Features enabled12={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,
    .vulkanMemoryModel=VK_TRUE, .vulkanMemoryModelDeviceScope=VK_TRUE};
  VkDeviceCreateInfo dci={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext=&enabled12,
    .pEnabledFeatures=&enabled, .queueCreateInfoCount=1, .pQueueCreateInfos=&qci};
  VK_CHECK(vkCreateDevice(vk_physical, &dci, NULL, &vk_device));
  vkGetDeviceQueue(vk_device, vk_family, 0, &vk_queue);
  return NULL;
}

static u64 gpu_span(void) {
  u64 limit=vk_properties.limits.maxStorageBufferRange;
  u64 wanted=(HEAP_OFF + CUBE * PAGE_LEN) * 8 + (64ull << 20);
  if (wanted < (128ull << 20)) wanted=128ull << 20;
  return limit < wanted ? limit : wanted;
}

static u32 vk_memory_type(const VkPhysicalDeviceMemoryProperties* mp, u32 bits,
    VkMemoryPropertyFlags required, VkMemoryPropertyFlags preferred) {
  u32 first=UINT32_MAX;
  for (u32 i=0; i<mp->memoryTypeCount; i++) {
    VkMemoryPropertyFlags flags=mp->memoryTypes[i].propertyFlags;
    if (!(bits & (1u<<i)) || (flags & required) != required) continue;
    if (first==UINT32_MAX) first=i;
    if ((flags & preferred) == preferred) return i;
  }
  return first;
}

static u64* gpu_map(u64 bytes) {
  if (bytes > vk_properties.limits.maxStorageBufferRange) err_fail("GPU heap exceeds maxStorageBufferRange");
  vk_bytes=bytes;
  VkBufferCreateInfo bci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size=bytes,
    .usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    .sharingMode=VK_SHARING_MODE_EXCLUSIVE};
  VK_CHECK(vkCreateBuffer(vk_device, &bci, NULL, &vk_buffer));
  VkMemoryRequirements req; vkGetBufferMemoryRequirements(vk_device, vk_buffer, &req);
  VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(vk_physical, &mp);
  u32 host=vk_memory_type(&mp, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
    VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT|VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
  u32 local=vk_memory_type(&mp, req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
  bool host_local=host!=UINT32_MAX &&
    (mp.memoryTypes[host].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)!=0;
  const char* force=getenv("BEND_VULKAN_FORCE_STAGING");
  bool forced=force && *force && strcmp(force, "0");
  bool staged=forced || host==UINT32_MAX || (!host_local && local!=UINT32_MAX);
  if (host==UINT32_MAX) err_fail("Vulkan host-visible staging memory unavailable");
  u32 main_type=staged ? (local!=UINT32_MAX ? local : host) : host;
  VkMemoryAllocateInfo mai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
    .allocationSize=req.size, .memoryTypeIndex=main_type};
  VK_CHECK(vkAllocateMemory(vk_device, &mai, NULL, &vk_memory));
  VK_CHECK(vkBindBufferMemory(vk_device, vk_buffer, vk_memory, 0));
  vk_staged=staged;
  if (!staged) {
    VK_CHECK(vkMapMemory(vk_device, vk_memory, 0, VK_WHOLE_SIZE, 0, &vk_map));
    vk_coherent=(mp.memoryTypes[host].propertyFlags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)!=0;
  } else {
    VkBufferCreateInfo sci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size=bytes,
      .usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,
      .sharingMode=VK_SHARING_MODE_EXCLUSIVE};
    VK_CHECK(vkCreateBuffer(vk_device, &sci, NULL, &vk_staging_buffer));
    VkMemoryRequirements sreq; vkGetBufferMemoryRequirements(vk_device, vk_staging_buffer, &sreq);
    u32 host2=vk_memory_type(&mp, sreq.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (host2==UINT32_MAX) err_fail("Vulkan host-visible staging memory unavailable");
    VkMemoryAllocateInfo smai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
      .allocationSize=sreq.size, .memoryTypeIndex=host2};
    VK_CHECK(vkAllocateMemory(vk_device, &smai, NULL, &vk_staging_memory));
    VK_CHECK(vkBindBufferMemory(vk_device, vk_staging_buffer, vk_staging_memory, 0));
    VK_CHECK(vkMapMemory(vk_device, vk_staging_memory, 0, VK_WHOLE_SIZE, 0, &vk_staging_map));
    vk_coherent=(mp.memoryTypes[host2].propertyFlags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)!=0;
    vk_map=vk_staging_map;
  }
  memset(vk_map, 0, bytes);
  return vk_map;
}

static bool gpu_make(const char* path) { return access(path, R_OK)==0; }

static void gpu_load(u64 bytes) {
  if (bytes!=vk_bytes) err_fail("Vulkan heap binding mismatch");
  FILE* file=fopen(gpu_path(), "rb");
  if (!file || fseek(file, 0, SEEK_END)) err_fail("compiled Vulkan .gpu module missing");
  long length=ftell(file);
  if (length<20 || length>64*1024*1024 || length%4 || fseek(file, 0, SEEK_SET)) err_fail("invalid Vulkan module size");
  u32* code=malloc((size_t)length);
  if (!code || fread(code, 1, (size_t)length, file)!=(size_t)length || code[0]!=0x07230203)
    err_fail("invalid Vulkan module bytes");
  fclose(file);
  VkShaderModuleCreateInfo smci={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
    .codeSize=(size_t)length, .pCode=code};
  VK_CHECK(vkCreateShaderModule(vk_device, &smci, NULL, &vk_shader)); free(code);
  VkDescriptorSetLayoutBinding bindings[2];
  for (u32 i=0; i<2; i++) bindings[i]=(VkDescriptorSetLayoutBinding){.binding=i,
    .descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount=1, .stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
  VkDescriptorSetLayoutCreateInfo slci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
    .bindingCount=2, .pBindings=bindings};
  VK_CHECK(vkCreateDescriptorSetLayout(vk_device, &slci, NULL, &vk_set_layout));
  VkDescriptorPoolSize pool_size={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2};
  VkDescriptorPoolCreateInfo dpci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
    .maxSets=1, .poolSizeCount=1, .pPoolSizes=&pool_size};
  VK_CHECK(vkCreateDescriptorPool(vk_device, &dpci, NULL, &vk_pool));
  VkDescriptorSetAllocateInfo dsai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
    .descriptorPool=vk_pool, .descriptorSetCount=1, .pSetLayouts=&vk_set_layout};
  VK_CHECK(vkAllocateDescriptorSets(vk_device, &dsai, &vk_set));
  VkDescriptorBufferInfo dbi={.buffer=vk_buffer, .range=bytes};
  VkWriteDescriptorSet writes[2];
  for (u32 i=0; i<2; i++) writes[i]=(VkWriteDescriptorSet){.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
    .dstSet=vk_set, .dstBinding=i, .descriptorCount=1, .descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo=&dbi};
  vkUpdateDescriptorSets(vk_device, 2, writes, 0, NULL);
  VkPushConstantRange push={.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT, .size=sizeof(u32)};
  VkPipelineLayoutCreateInfo plci={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
    .setLayoutCount=1, .pSetLayouts=&vk_set_layout, .pushConstantRangeCount=1, .pPushConstantRanges=&push};
  VK_CHECK(vkCreatePipelineLayout(vk_device, &plci, NULL, &vk_layout));
  VkComputePipelineCreateInfo cpci={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
    .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
      .stage=VK_SHADER_STAGE_COMPUTE_BIT, .module=vk_shader, .pName="main"}, .layout=vk_layout};
  VK_CHECK(vkCreateComputePipelines(vk_device, VK_NULL_HANDLE, 1, &cpci, NULL, &vk_pipeline));
  VkCommandPoolCreateInfo pci={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
    .flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex=vk_family};
  VK_CHECK(vkCreateCommandPool(vk_device, &pci, NULL, &vk_commands));
  VkCommandBufferAllocateInfo cbai={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
    .commandPool=vk_commands, .level=VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount=1};
  VK_CHECK(vkAllocateCommandBuffers(vk_device, &cbai, &vk_command));
  VkFenceCreateInfo fci={.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VK_CHECK(vkCreateFence(vk_device, &fci, NULL, &vk_fence));
}

static void gpu_kernel(u32 pass, u32 groups) {
  vkCmdPushConstants(vk_command, vk_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pass, &pass);
  vkCmdDispatch(vk_command, groups, 1, 1);
  VkMemoryBarrier barrier={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
    .srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT};
  vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
    VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
  vk_dispatches++;
}

static void gpu_pass(u32 frontier) {
  VkMappedMemoryRange range={.sType=VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
    .memory=vk_staged ? vk_staging_memory : vk_memory, .size=VK_WHOLE_SIZE};
  if (!vk_coherent) VK_CHECK(vkFlushMappedMemoryRanges(vk_device, 1, &range));
  VK_CHECK(vkResetFences(vk_device, 1, &vk_fence));
  VK_CHECK(vkResetCommandBuffer(vk_command, 0));
  VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
    .flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
  VK_CHECK(vkBeginCommandBuffer(vk_command, &begin));
  vkCmdBindPipeline(vk_command, VK_PIPELINE_BIND_POINT_COMPUTE, vk_pipeline);
  vkCmdBindDescriptorSets(vk_command, VK_PIPELINE_BIND_POINT_COMPUTE, vk_layout, 0, 1, &vk_set, 0, NULL);
  if (vk_staged) {
    VkMemoryBarrier upload={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_HOST_WRITE_BIT, .dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_HOST_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &upload, 0, NULL, 0, NULL);
    VkBufferCopy copy={.srcOffset=0, .dstOffset=0, .size=vk_bytes};
    vkCmdCopyBuffer(vk_command, vk_staging_buffer, vk_buffer, 1, &copy);
    VkMemoryBarrier ready={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &ready, 0, NULL, 0, NULL);
  } else {
    VkMemoryBarrier pre={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_HOST_WRITE_BIT, .dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_HOST_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &pre, 0, NULL, 0, NULL);
  }
  gpu_run(frontier);
  if (vk_staged) {
    VkMemoryBarrier download={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &download, 0, NULL, 0, NULL);
    VkBufferCopy copy={.srcOffset=0, .dstOffset=0, .size=vk_bytes};
    vkCmdCopyBuffer(vk_command, vk_buffer, vk_staging_buffer, 1, &copy);
    VkMemoryBarrier finish={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask=VK_ACCESS_HOST_READ_BIT|VK_ACCESS_HOST_WRITE_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &finish, 0, NULL, 0, NULL);
  } else {
    VkMemoryBarrier post={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask=VK_ACCESS_HOST_READ_BIT|VK_ACCESS_HOST_WRITE_BIT};
    vkCmdPipelineBarrier(vk_command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &post, 0, NULL, 0, NULL);
  }
  VK_CHECK(vkEndCommandBuffer(vk_command));
  VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount=1, .pCommandBuffers=&vk_command};
  if (getenv("BEND_VULKAN_TRACE")) fprintf(stderr, "Vulkan submit frontier=%u\n", frontier);
  VK_CHECK(vkQueueSubmit(vk_queue, 1, &submit, vk_fence));
  VK_CHECK(vkWaitForFences(vk_device, 1, &vk_fence, VK_TRUE, 300000000000ull));
  if (!vk_coherent) VK_CHECK(vkInvalidateMappedMemoryRanges(vk_device, 1, &range));
}
