/***************************************************************************
 # Copyright (c) 2015-23, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY
 # EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 # PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 # OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 **************************************************************************/
#include "NGXWrapper.h"
#include "Core/API/NativeHandleTraits.h"
#include "Core/API/NativeFormats.h"

#if FALCOR_WINDOWS
// For reporting which nvngx_dlss*.dll NGX actually mapped -- see logLoadedFeatureDll().
#include <windows.h>
#pragma comment(lib, "version.lib")
#endif

#if FALCOR_HAS_D3D12
#include <d3d12.h>
#include <nvsdk_ngx.h>
#include <nvsdk_ngx_helpers.h>
#if FALCOR_HAS_DLSSD
// Ray Reconstruction. Only present in SDKs from the 310.x line -- see DLSSPass/README.md.
#include <nvsdk_ngx_helpers_dlssd.h>
#endif
#endif

#if FALCOR_HAS_VULKAN
#include <vulkan/vulkan.h>
#include <nvsdk_ngx_vk.h>
#include <nvsdk_ngx_helpers_vk.h>
#endif

#include <cstdio>
#include <cstdarg>

#define THROW_IF_FAILED(call)                                                     \
    {                                                                             \
        NVSDK_NGX_Result result_ = call;                                          \
        if (NVSDK_NGX_FAILED(result_))                                            \
            FALCOR_THROW(#call " failed with error {}", resultToString(result_)); \
    }

namespace Falcor
{
namespace
{
const uint64_t kAppID = 231313132;

std::string resultToString(NVSDK_NGX_Result result)
{
    char buf[1024];
    snprintf(buf, sizeof(buf), "(code: 0x%08x, info: %ls)", result, GetNGXResultAsString(result));
    buf[sizeof(buf) - 1] = '\0';
    return std::string(buf);
}

#if FALCOR_HAS_VULKAN
VkImageAspectFlags getAspectMaskFromFormat(VkFormat format)
{
    switch (format)
    {
    case VK_FORMAT_D16_UNORM_S8_UINT:
    case VK_FORMAT_D24_UNORM_S8_UINT:
    case VK_FORMAT_D32_SFLOAT_S8_UINT:
        return VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT;
    case VK_FORMAT_D16_UNORM:
    case VK_FORMAT_D32_SFLOAT:
    case VK_FORMAT_X8_D24_UNORM_PACK32:
        return VK_IMAGE_ASPECT_DEPTH_BIT;
    case VK_FORMAT_S8_UINT:
        return VK_IMAGE_ASPECT_STENCIL_BIT;
    default:
        return VK_IMAGE_ASPECT_COLOR_BIT;
    }
}
#endif

} // namespace

NGXWrapper::NGXWrapper(
    ref<Device> pDevice,
    const std::filesystem::path& applicationDataPath,
    const std::filesystem::path& featureSearchPath
)
    : mpDevice(pDevice)
{
    initializeNGX(applicationDataPath, featureSearchPath);
}

NGXWrapper::~NGXWrapper()
{
    shutdownNGX();
}

std::shared_ptr<NGXWrapper> NGXWrapper::acquire(
    ref<Device> pDevice,
    const std::filesystem::path& applicationDataPath,
    const std::filesystem::path& featureSearchPath
)
{
    // One NGX session per device, shared by every pass that needs one. weak_ptr so the session is
    // torn down once no pass holds it, rather than outliving the device.
    //
    // The search path is part of the identity: it decides WHICH nvngx_dlss*.dll -- and therefore
    // which trained network -- NGX loads. Returning a session created against a different path would
    // silently hand back the wrong model, which is precisely the confusion the CNN/transformer
    // comparison exists to resolve. NVSDK_NGX_*_Init is per-device, so a second path on a live
    // device is not something we can satisfy; say so rather than quietly using the first.
    static std::mutex sMutex;
    static std::map<Device*, std::pair<std::filesystem::path, std::weak_ptr<NGXWrapper>>> sSessions;

    std::lock_guard<std::mutex> lock(sMutex);

    auto it = sSessions.find(pDevice.get());
    if (it != sSessions.end())
    {
        if (auto existing = it->second.second.lock())
        {
            if (it->second.first != featureSearchPath)
                FALCOR_THROW(
                    "NGX is already initialized on this device with feature search path '{}', so '{}' "
                    "cannot also be used. Every DLSS pass in one graph must select the same SDK "
                    "variant -- run the two variants as separate processes to compare them.",
                    it->second.first, featureSearchPath
                );
            return existing;
        }
    }

    auto created = std::make_shared<NGXWrapper>(pDevice, applicationDataPath, featureSearchPath);
    sSessions[pDevice.get()] = {featureSearchPath, created};
    return created;
}

void NGXWrapper::logLoadedFeatureDll(const char* moduleName)
{
    // Which DLL NGX actually loaded is the only thing that determines which network runs, and the
    // search path is a *hint* -- NGX falls back to the executable directory. Report the module that
    // is really mapped into the process, so a silent fallback to the wrong model cannot go unnoticed.
#if FALCOR_WINDOWS
    HMODULE hModule = GetModuleHandleA(moduleName);
    if (hModule == nullptr)
    {
        logWarning("[NGX] {} is not loaded", moduleName);
        return;
    }

    char path[MAX_PATH] = {};
    if (GetModuleFileNameA(hModule, path, MAX_PATH) == 0)
        return;

    std::string version = "unknown";
    DWORD handle = 0;
    DWORD size = GetFileVersionInfoSizeA(path, &handle);
    if (size > 0)
    {
        std::vector<uint8_t> data(size);
        VS_FIXEDFILEINFO* pInfo = nullptr;
        UINT infoLen = 0;
        if (GetFileVersionInfoA(path, 0, size, data.data()) &&
            VerQueryValueA(data.data(), "\\", reinterpret_cast<LPVOID*>(&pInfo), &infoLen) && pInfo != nullptr)
        {
            version = fmt::format(
                "{}.{}.{}.{}", HIWORD(pInfo->dwFileVersionMS), LOWORD(pInfo->dwFileVersionMS),
                HIWORD(pInfo->dwFileVersionLS), LOWORD(pInfo->dwFileVersionLS)
            );
        }
    }
    logInfo("[NGX] loaded {} version {} from {}", moduleName, version, path);
#endif
}

void NGXWrapper::initializeNGX(const std::filesystem::path& applicationDataPath, const std::filesystem::path& featureSearchPath)
{
    NVSDK_NGX_Result result = NVSDK_NGX_Result_Fail;

    NVSDK_NGX_FeatureCommonInfo featureInfo = {};
    const wchar_t* pathList[] = {featureSearchPath.c_str()};
    featureInfo.PathListInfo.Length = 1;
    featureInfo.PathListInfo.Path = const_cast<wchar_t**>(&pathList[0]);

    switch (mpDevice->getType())
    {
    case Device::Type::D3D12:
#if FALCOR_HAS_D3D12
        result = NVSDK_NGX_D3D12_Init(kAppID, applicationDataPath.c_str(), mpDevice->getNativeHandle().as<ID3D12Device*>(), &featureInfo);
#endif
        break;
    case Device::Type::Vulkan:
#if FALCOR_HAS_VULKAN
        result = NVSDK_NGX_VULKAN_Init(
            kAppID,
            applicationDataPath.c_str(),
            mpDevice->getNativeHandle(0).as<VkInstance>(),
            mpDevice->getNativeHandle(1).as<VkPhysicalDevice>(),
            mpDevice->getNativeHandle(2).as<VkDevice>(),
            nullptr,
            nullptr,
            &featureInfo
        );
#endif
        break;
    }

    if (NVSDK_NGX_FAILED(result))
    {
        if (result == NVSDK_NGX_Result_FAIL_FeatureNotSupported || result == NVSDK_NGX_Result_FAIL_PlatformError)
        {
            FALCOR_THROW("NVIDIA NGX is not available on this hardware/platform " + resultToString(result));
        }
        else
        {
            FALCOR_THROW("Failed to initialize NGX " + resultToString(result));
        }
    }

    mInitialized = true;

    switch (mpDevice->getType())
    {
    case Device::Type::D3D12:
#if FALCOR_HAS_D3D12
        THROW_IF_FAILED(NVSDK_NGX_D3D12_GetCapabilityParameters(&mpParameters));
#endif
        break;
    case Device::Type::Vulkan:
#if FALCOR_HAS_VULKAN
        THROW_IF_FAILED(NVSDK_NGX_VULKAN_GetCapabilityParameters(&mpParameters));
#endif
        break;
    }

    // Currently, the SDK and this sample are not in sync.  The sample is a bit forward looking,
    // in this case.  This will likely be resolved very shortly, and therefore, the code below
    // should be thought of as needed for a smooth user experience.
#if defined(NVSDK_NGX_Parameter_SuperSampling_NeedsUpdatedDriver) && defined(NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMajor) && \
    defined(NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMinor)

    // If NGX Successfully initialized then it should set those flags in return
    int needsUpdatedDriver = 0;
    if (!NVSDK_NGX_FAILED(mpParameters->Get(NVSDK_NGX_Parameter_SuperSampling_NeedsUpdatedDriver, &needsUpdatedDriver)) &&
        needsUpdatedDriver)
    {
        std::string message = "NVIDIA DLSS cannot be loaded due to outdated driver.";
        unsigned int majorVersion = 0;
        unsigned int minorVersion = 0;
        if (!NVSDK_NGX_FAILED(mpParameters->Get(NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMajor, &majorVersion)) &&
            !NVSDK_NGX_FAILED(mpParameters->Get(NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMinor, &minorVersion)))
        {
            message += fmt::format("\nMinimum driver version required: {}.{}", majorVersion, minorVersion);
        }
        FALCOR_THROW(message);
    }
#endif

    // Per-feature availability. Neither probe throws on its own: a machine with Super Resolution
    // but no Ray Reconstruction (or an SDK without nvngx_dlssd.dll) must still run the SR path.
    // Only the case where BOTH are unusable is fatal.
    //
    // The capability parameters are a plain string-keyed map answered by the driver, so the RR keys
    // can be queried even against an SDK with no DLSS-D headers. Note that "available=0" with
    // needsUpdatedDriver=0 and minDriver=0.0 usually means nvngx_dlssd.dll is simply absent from the
    // feature search path -- NGX cannot distinguish that from unsupported hardware.
    int srAvailable = 0;
    result = mpParameters->Get(NVSDK_NGX_Parameter_SuperSampling_Available, &srAvailable);
    mSRAvailable = !NVSDK_NGX_FAILED(result) && srAvailable != 0;

    int rrAvailable = 0;
    NVSDK_NGX_Result rrResult = mpParameters->Get("SuperSamplingDenoising.Available", &rrAvailable);
    int rrNeedsDriver = 0;
    mpParameters->Get("SuperSamplingDenoising.NeedsUpdatedDriver", &rrNeedsDriver);
    unsigned int rrMajor = 0, rrMinor = 0;
    mpParameters->Get("SuperSamplingDenoising.MinDriverVersionMajor", &rrMajor);
    mpParameters->Get("SuperSamplingDenoising.MinDriverVersionMinor", &rrMinor);
    mRRAvailable = !NVSDK_NGX_FAILED(rrResult) && rrAvailable != 0 && !rrNeedsDriver;

    logInfo(
        "NGX features: SuperResolution={} RayReconstruction={} (rr needsUpdatedDriver={} minDriver={}.{})",
        mSRAvailable,
        mRRAvailable,
        rrNeedsDriver,
        rrMajor,
        rrMinor
    );

    if (!mSRAvailable && !mRRAvailable)
    {
        FALCOR_THROW("No NVIDIA NGX feature available on this hardware/platform " + resultToString(result));
    }
}

void NGXWrapper::shutdownNGX()
{
    if (mInitialized)
    {
        mpDevice->wait();

        if (mpFeatureSR != nullptr)
            releaseDLSS();
#if FALCOR_HAS_DLSSD
        if (mpFeatureRR != nullptr)
            releaseDLSSD();
#endif

        switch (mpDevice->getType())
        {
        case Device::Type::D3D12:
#if FALCOR_HAS_D3D12
            THROW_IF_FAILED(NVSDK_NGX_D3D12_DestroyParameters(mpParameters));
            THROW_IF_FAILED(NVSDK_NGX_D3D12_Shutdown1(mpDevice->getNativeHandle().as<ID3D12Device*>()));
#endif
            break;
        case Device::Type::Vulkan:
#if FALCOR_HAS_VULKAN
            THROW_IF_FAILED(NVSDK_NGX_VULKAN_DestroyParameters(mpParameters));
            THROW_IF_FAILED(NVSDK_NGX_VULKAN_Shutdown1(mpDevice->getNativeHandle(2).as<VkDevice>()));
#endif
            break;
        }

        mInitialized = false;
    }
}

#if FALCOR_HAS_DLSSD
void NGXWrapper::initializeDLSSD(
    RenderContext* pRenderContext,
    uint2 maxRenderSize,
    uint2 displayOutSize,
    bool isContentHDR,
    NVSDK_NGX_PerfQuality_Value perfQuality,
    uint32_t renderPreset
)
{
    if (!mRRAvailable)
        FALCOR_THROW(
            "DLSS Ray Reconstruction is not available. If the driver is recent enough, check that "
            "nvngx_dlssd.dll sits next to the executable -- NGX reports a missing feature DLL "
            "identically to unsupported hardware."
        );

    if (mpFeatureRR != nullptr)
        releaseDLSSD();

    unsigned int creationNodeMask = 1;
    unsigned int visibilityNodeMask = 1;

    int createFlags = NVSDK_NGX_DLSS_Feature_Flags_None;
    // Motion vectors are at render resolution, same as the Super Resolution path.
    createFlags |= NVSDK_NGX_DLSS_Feature_Flags_MVLowRes;
    createFlags |= isContentHDR ? NVSDK_NGX_DLSS_Feature_Flags_IsHDR : 0;
    // DepthInverted is deliberately not set: we feed linear view Z, for which it is meaningless.

    NVSDK_NGX_DLSSD_Create_Params dlssdParams = {};
    dlssdParams.InDenoiseMode = NVSDK_NGX_DLSS_Denoise_Mode_DLUnified;
    // Unpacked: roughness arrives in its own texture rather than normals.w. One less packing
    // convention to get wrong while bringing the feature up.
    dlssdParams.InRoughnessMode = NVSDK_NGX_DLSS_Roughness_Mode_Unpacked;
    // The whole reason this renderer fits RR: it already emits linear view Z.
    dlssdParams.InUseHWDepth = NVSDK_NGX_DLSS_Depth_Type_Linear;
    dlssdParams.InWidth = maxRenderSize.x;
    dlssdParams.InHeight = maxRenderSize.y;
    dlssdParams.InTargetWidth = displayOutSize.x;
    dlssdParams.InTargetHeight = displayOutSize.y;
    dlssdParams.InPerfQualityValue = perfQuality;
    dlssdParams.InFeatureCreateFlags = createFlags;

    // The render preset must be set on the parameter block before the create call -- and NGX reads
    // the hint belonging to the quality level being created, NOT a single global one. Setting only
    // the DLAA hint (as this did originally) means every upscaling profile silently ignored the
    // preset and got NGX's default model. Set them all: only the one matching InPerfQualityValue is
    // consulted, so there is no ambiguity, and the create call cannot miss it.
    if (renderPreset != 0)
    {
        for (const char* hint : {NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_DLAA,
                                 NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_Quality,
                                 NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_Balanced,
                                 NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_Performance,
                                 NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_UltraPerformance,
                                 NVSDK_NGX_Parameter_RayReconstruction_Hint_Render_Preset_UltraQuality})
        {
            NVSDK_NGX_Parameter_SetUI(mpParameters, hint, renderPreset);
        }
    }

    switch (mpDevice->getType())
    {
    case Device::Type::D3D12:
    {
#if FALCOR_HAS_D3D12
        // The submit()/create/submit() sandwich matches initializeDLSS(): NGX records into Falcor's
        // currently-open command list, so it must be flushed either side.
        pRenderContext->submit();
        ID3D12GraphicsCommandList* pCommandList =
            pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
        THROW_IF_FAILED(
            NGX_D3D12_CREATE_DLSSD_EXT(pCommandList, creationNodeMask, visibilityNodeMask, &mpFeatureRR, mpParameters, &dlssdParams)
        );
        pRenderContext->submit();
#endif
        break;
    }
    default:
        FALCOR_THROW("DLSS Ray Reconstruction is only implemented for D3D12.");
    }

    logInfo("DLSS Ray Reconstruction initialized: {}x{} -> {}x{}", maxRenderSize.x, maxRenderSize.y, displayOutSize.x, displayOutSize.y);
    logLoadedFeatureDll("nvngx_dlssd.dll");
}

void NGXWrapper::releaseDLSSD()
{
    if (mpFeatureRR)
    {
        mpDevice->wait();
#if FALCOR_HAS_D3D12
        THROW_IF_FAILED(NVSDK_NGX_D3D12_ReleaseFeature(mpFeatureRR));
#endif
        mpFeatureRR = nullptr;
    }
}

bool NGXWrapper::evaluateDLSSD(
    RenderContext* pRenderContext,
    const DLSSDEvalInputs& in,
    bool resetAccumulation,
    float2 jitterOffset,
    float2 motionVectorScale,
    const float4x4* pWorldToView,
    const float4x4* pViewToClip,
    float frameTimeDeltaMs
) const
{
    if (!mpFeatureRR)
        return false;

#if FALCOR_HAS_D3D12
    // Every input must be in ShaderResource and the output in UnorderedAccess before NGX runs.
    // A missed barrier here is a silent debug-layer error plus garbage output, and there are
    // now seven inputs rather than three.
    Texture* const srvInputs[] = {
        in.color, in.depth, in.motionVectors, in.diffuseAlbedo, in.specularAlbedo, in.normals, in.roughness, in.exposure};
    for (Texture* pTex : srvInputs)
    {
        if (pTex)
            pRenderContext->resourceBarrier(pTex, Resource::State::ShaderResource);
    }
    pRenderContext->resourceBarrier(in.output, Resource::State::UnorderedAccess);

    auto native = [](Texture* pTex) -> ID3D12Resource*
    { return pTex ? pTex->getNativeHandle().as<ID3D12Resource*>() : nullptr; };

    NVSDK_NGX_D3D12_DLSSD_Eval_Params evalParams = {};
    evalParams.pInColor = native(in.color);
    evalParams.pInOutput = native(in.output);
    evalParams.pInDepth = native(in.depth);
    evalParams.pInMotionVectors = native(in.motionVectors);
    evalParams.pInDiffuseAlbedo = native(in.diffuseAlbedo);
    evalParams.pInSpecularAlbedo = native(in.specularAlbedo);
    evalParams.pInNormals = native(in.normals);
    evalParams.pInRoughness = native(in.roughness);
    evalParams.pInExposureTexture = native(in.exposure);
    evalParams.InJitterOffsetX = jitterOffset.x;
    evalParams.InJitterOffsetY = jitterOffset.y;
    evalParams.InReset = resetAccumulation ? 1 : 0;
    evalParams.InMVScaleX = motionVectorScale.x;
    evalParams.InMVScaleY = motionVectorScale.y;
    evalParams.InRenderSubrectDimensions.Width = in.color->getWidth();
    evalParams.InRenderSubrectDimensions.Height = in.color->getHeight();
    // Optional but meaningful: RR reprojects using these, and scales denoising strength by the
    // frame time implied against the motion-vector magnitudes. Passing nullptr/0 (as the
    // zero-initialised struct would) silently gives up both.
    evalParams.pInWorldToViewMatrix = pWorldToView ? const_cast<float*>(reinterpret_cast<const float*>(pWorldToView)) : nullptr;
    evalParams.pInViewToClipMatrix = pViewToClip ? const_cast<float*>(reinterpret_cast<const float*>(pViewToClip)) : nullptr;
    evalParams.InFrameTimeDeltaInMsec = frameTimeDeltaMs;

    ID3D12GraphicsCommandList* pCommandList =
        pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
    NVSDK_NGX_Result result = NGX_D3D12_EVALUATE_DLSSD_EXT(pCommandList, mpFeatureRR, mpParameters, &evalParams);

    // Non-fatal, matching evaluateDLSS(): a bad frame should not take the application down.
    if (NVSDK_NGX_FAILED(result))
    {
        logWarning("Failed to evaluate DLSS-D feature: {}", resultToString(result));
        return false;
    }

    // NGX wrote into Falcor's command list behind its back.
    pRenderContext->setPendingCommands(true);
    pRenderContext->uavBarrier(in.output);
    pRenderContext->submit();
    return true;
#else
    return false;
#endif
}
#endif // FALCOR_HAS_DLSSD

void NGXWrapper::initializeDLSS(
    RenderContext* pRenderContext,
    uint2 maxRenderSize,
    uint2 displayOutSize,
    Texture* pTarget,
    bool isContentHDR,
    bool depthInverted,
    NVSDK_NGX_PerfQuality_Value perfQuality,
    uint32_t renderPreset
)
{
    unsigned int creationNodeMask = 1;
    unsigned int visibilityNodeMask = 1;

    // Next create features
    int createFlags = NVSDK_NGX_DLSS_Feature_Flags_None;
    createFlags |= NVSDK_NGX_DLSS_Feature_Flags_MVLowRes;
    createFlags |= isContentHDR ? NVSDK_NGX_DLSS_Feature_Flags_IsHDR : 0;
    createFlags |= depthInverted ? NVSDK_NGX_DLSS_Feature_Flags_DepthInverted : 0;

    NVSDK_NGX_DLSS_Create_Params dlssParams = {};

    dlssParams.Feature.InWidth = maxRenderSize.x;
    dlssParams.Feature.InHeight = maxRenderSize.y;
    dlssParams.Feature.InTargetWidth = displayOutSize.x;
    dlssParams.Feature.InTargetHeight = displayOutSize.y;
    dlssParams.Feature.InPerfQualityValue = perfQuality;
    dlssParams.InFeatureCreateFlags = createFlags;

    // As in initializeDLSSD: NGX consults the hint belonging to the quality level being created, so
    // setting a single one would be ignored by every other profile.
    if (renderPreset != 0)
    {
        for (const char* hint : {NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA,
                                 NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality,
                                 NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced,
                                 NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance,
                                 NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance,
                                 NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraQuality})
        {
            NVSDK_NGX_Parameter_SetUI(mpParameters, hint, renderPreset);
        }
    }

    switch (mpDevice->getType())
    {
    case Device::Type::D3D12:
    {
#if FALCOR_HAS_D3D12
        pRenderContext->submit();
        ID3D12GraphicsCommandList* pCommandList =
            pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
        THROW_IF_FAILED(NGX_D3D12_CREATE_DLSS_EXT(pCommandList, creationNodeMask, visibilityNodeMask, &mpFeatureSR, mpParameters, &dlssParams)
        );
        pRenderContext->submit();
        logLoadedFeatureDll("nvngx_dlss.dll");
#endif
        break;
    }
    case Device::Type::Vulkan:
    {
#if FALCOR_HAS_VULKAN
        pRenderContext->submit();
        VkCommandBuffer vkCommandBuffer = pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<VkCommandBuffer>();
        THROW_IF_FAILED(
            NGX_VULKAN_CREATE_DLSS_EXT(vkCommandBuffer, creationNodeMask, visibilityNodeMask, &mpFeatureSR, mpParameters, &dlssParams)
        );
        pRenderContext->submit();
#endif
        break;
    }
    }
}

void NGXWrapper::releaseDLSS()
{
    if (mpFeatureSR)
    {
        mpDevice->wait();

        switch (mpDevice->getType())
        {
        case Device::Type::D3D12:
#if FALCOR_HAS_D3D12
            THROW_IF_FAILED(NVSDK_NGX_D3D12_ReleaseFeature(mpFeatureSR));
#endif
            break;
        case Device::Type::Vulkan:
#if FALCOR_HAS_VULKAN
            THROW_IF_FAILED(NVSDK_NGX_VULKAN_ReleaseFeature(mpFeatureSR));
#endif
            break;
        }
        mpFeatureSR = nullptr;
    }
}

NGXWrapper::OptimalSettings NGXWrapper::queryOptimalSettings(uint2 displaySize, NVSDK_NGX_PerfQuality_Value perfQuality) const
{
    OptimalSettings settings;

    THROW_IF_FAILED(NGX_DLSS_GET_OPTIMAL_SETTINGS(
        mpParameters,
        displaySize.x,
        displaySize.y,
        perfQuality,
        &settings.optimalRenderSize.x,
        &settings.optimalRenderSize.y,
        &settings.maxRenderSize.x,
        &settings.maxRenderSize.y,
        &settings.minRenderSize.x,
        &settings.minRenderSize.y,
        &settings.sharpness
    ));

    // Depending on what version of DLSS DLL is being used, a sharpness of > 1.f was possible.
    settings.sharpness = math::clamp(settings.sharpness, -1.f, 1.f);

    return settings;
}

bool NGXWrapper::evaluateDLSS(
    RenderContext* pRenderContext,
    Texture* pUnresolvedColor,
    Texture* pResolvedColor,
    Texture* pMotionVectors,
    Texture* pDepth,
    Texture* pExposure,
    bool resetAccumulation,
    float sharpness,
    float2 jitterOffset,
    float2 motionVectorScale
) const
{
    if (!mpFeatureSR)
        return false;

    // In DLSS v2, the target is already upsampled (while in v1, the upsampling is handled in a later pass)
    // >= rather than >: DLAA runs at native resolution, where output == input.
    FALCOR_ASSERT(pResolvedColor->getWidth() >= pUnresolvedColor->getWidth() && pResolvedColor->getHeight() >= pUnresolvedColor->getHeight());

    bool success = true;

    switch (mpDevice->getType())
    {
    case Device::Type::D3D12:
    {
#if FALCOR_HAS_D3D12
        pRenderContext->resourceBarrier(pUnresolvedColor, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pMotionVectors, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pDepth, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pResolvedColor, Resource::State::UnorderedAccess);

        ID3D12Resource* unresolvedColorBuffer = pUnresolvedColor->getNativeHandle().as<ID3D12Resource*>();
        ID3D12Resource* motionVectorsBuffer = pMotionVectors->getNativeHandle().as<ID3D12Resource*>();
        ID3D12Resource* resolvedColorBuffer = pResolvedColor->getNativeHandle().as<ID3D12Resource*>();
        ID3D12Resource* depthBuffer = pDepth->getNativeHandle().as<ID3D12Resource*>();
        ID3D12Resource* exposureBuffer = pExposure ? pExposure->getNativeHandle().as<ID3D12Resource*>() : nullptr;

        NVSDK_NGX_D3D12_DLSS_Eval_Params evalParams = {};

        evalParams.Feature.pInColor = unresolvedColorBuffer;
        evalParams.Feature.pInOutput = resolvedColorBuffer;
        evalParams.Feature.InSharpness = sharpness;
        evalParams.pInDepth = depthBuffer;
        evalParams.pInMotionVectors = motionVectorsBuffer;
        evalParams.InJitterOffsetX = jitterOffset.x;
        evalParams.InJitterOffsetY = jitterOffset.y;
        evalParams.InReset = resetAccumulation ? 1 : 0;
        evalParams.InRenderSubrectDimensions.Width = pUnresolvedColor->getWidth();
        evalParams.InRenderSubrectDimensions.Height = pUnresolvedColor->getHeight();
        evalParams.InMVScaleX = motionVectorScale.x;
        evalParams.InMVScaleY = motionVectorScale.y;
        evalParams.pInExposureTexture = exposureBuffer;

        ID3D12GraphicsCommandList* pCommandList =
            pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
        NVSDK_NGX_Result result = NGX_D3D12_EVALUATE_DLSS_EXT(pCommandList, mpFeatureSR, mpParameters, &evalParams);
        if (NVSDK_NGX_FAILED(result))
        {
            logWarning("Failed to NGX_D3D12_EVALUATE_DLSS_EXT for DLSS: {}", resultToString(result));
            success = false;
        }

        pRenderContext->setPendingCommands(true);
        pRenderContext->uavBarrier(pResolvedColor);
        // TODO: Get rid of the flush
        pRenderContext->submit();
#endif // FALCOR_HAS_D3D12
        break;
    }
    case Device::Type::Vulkan:
    {
#if FALCOR_HAS_VULKAN
        pRenderContext->resourceBarrier(pUnresolvedColor, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pMotionVectors, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pDepth, Resource::State::ShaderResource);
        pRenderContext->resourceBarrier(pResolvedColor, Resource::State::UnorderedAccess);

        auto getImageView = [](Texture* pTexture, bool isUAV = false) -> NVSDK_NGX_Resource_VK
        {
            if (!pTexture)
                return {};

            VkImageView imageView = isUAV ? pTexture->getUAV()->getNativeHandle().as<VkImageView>()
                                          : pTexture->getSRV(0, 1)->getNativeHandle().as<VkImageView>();
            VkImage image = pTexture->getNativeHandle().as<VkImage>();
            VkFormat format = getVulkanFormat(pTexture->getFormat());
            VkImageSubresourceRange range;
            range.aspectMask = getAspectMaskFromFormat(format);
            range.baseMipLevel = 0;
            range.levelCount = 1;
            range.baseArrayLayer = 0;
            range.layerCount = 1;
            return NVSDK_NGX_Create_ImageView_Resource_VK(
                imageView, image, range, format, pTexture->getWidth(), pTexture->getHeight(), isUAV
            );
        };

        NVSDK_NGX_Resource_VK unresolvedColorBuffer = getImageView(pUnresolvedColor);
        NVSDK_NGX_Resource_VK motionVectorsBuffer = getImageView(pMotionVectors);
        NVSDK_NGX_Resource_VK resolvedColorBuffer = getImageView(pResolvedColor, true);
        NVSDK_NGX_Resource_VK depthBuffer = getImageView(pDepth);
        NVSDK_NGX_Resource_VK exposureBuffer = getImageView(pExposure);

        NVSDK_NGX_VK_DLSS_Eval_Params evalParams = {};

        evalParams.Feature.pInColor = &unresolvedColorBuffer;
        evalParams.Feature.pInOutput = &resolvedColorBuffer;
        evalParams.Feature.InSharpness = sharpness;
        evalParams.pInDepth = &depthBuffer;
        evalParams.pInMotionVectors = &motionVectorsBuffer;
        evalParams.InJitterOffsetX = jitterOffset.x;
        evalParams.InJitterOffsetY = jitterOffset.y;
        evalParams.InReset = resetAccumulation ? 1 : 0;
        evalParams.InRenderSubrectDimensions.Width = pUnresolvedColor->getWidth();
        evalParams.InRenderSubrectDimensions.Height = pUnresolvedColor->getHeight();
        evalParams.InMVScaleX = motionVectorScale.x;
        evalParams.InMVScaleY = motionVectorScale.y;
        evalParams.pInExposureTexture = &exposureBuffer;

        VkCommandBuffer vkCommandBuffer = pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<VkCommandBuffer>();
        NVSDK_NGX_Result result = NGX_VULKAN_EVALUATE_DLSS_EXT(vkCommandBuffer, mpFeatureSR, mpParameters, &evalParams);
        if (NVSDK_NGX_FAILED(result))
        {
            logWarning("Failed to NGX_VULKAN_EVALUATE_DLSS_EXT for DLSS: {}", resultToString(result));
            success = false;
        }

        pRenderContext->setPendingCommands(true);
        pRenderContext->uavBarrier(pResolvedColor);
        // TODO: Get rid of the flush
        pRenderContext->submit();
#endif
        break;
    }
    }

    return success;
}

} // namespace Falcor
