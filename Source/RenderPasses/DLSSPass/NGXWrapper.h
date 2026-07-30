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
#pragma once
#include "Falcor.h"
#include <map>
#include <memory>
#include <mutex>

#include <nvsdk_ngx_defs.h>

#include <filesystem>

// Forward declarations from NGX library.
struct NVSDK_NGX_Parameter;
struct NVSDK_NGX_Handle;

namespace Falcor
{
/**
 * This is a wrapper around the NGX functionality for DLSS.
 * It is seperated to provide focus to the calls specific to NGX for code sample purposes.
 */
class NGXWrapper
{
public:
    struct OptimalSettings
    {
        float sharpness;
        uint2 optimalRenderSize;
        uint2 minRenderSize;
        uint2 maxRenderSize;
    };

    /// Constructor. Throws an exception if unable to initialize NGX.
    NGXWrapper(ref<Device> pDevice, const std::filesystem::path& applicationDataPath, const std::filesystem::path& featureSearchPath);
    ~NGXWrapper();

    /// Get the shared NGX session for a device, creating it on first use.
    ///
    /// NGX is initialised and shut down per *device*, not per pass: NVSDK_NGX_D3D12_Init and
    /// _Shutdown1 both take the device. Two passes each owning their own wrapper (e.g. DLSSPass
    /// and DLSSDPass side by side in a comparison graph, which is exactly the intended use) would
    /// init NGX twice and, worse, the first pass destroyed would shut NGX down underneath the
    /// second. Callers hold a shared_ptr; the session is released when the last one goes away.
    static std::shared_ptr<NGXWrapper> acquire(
        ref<Device> pDevice,
        const std::filesystem::path& applicationDataPath,
        const std::filesystem::path& featureSearchPath
    );

    /// Query optimal DLSS settings for a given resolution and performance/quality profile.
    OptimalSettings queryOptimalSettings(uint2 displaySize, NVSDK_NGX_PerfQuality_Value perfQuality) const;

    /// Initialize DLSS. Throws an exception if unable to initialize.
    void initializeDLSS(
        RenderContext* pRenderContext,
        uint2 maxRenderSize,
        uint2 displayOutSize,
        Texture* pTarget,
        bool isContentHDR,
        bool depthInverted,
        NVSDK_NGX_PerfQuality_Value perfQuality = NVSDK_NGX_PerfQuality_Value_MaxPerf,
        /// NVSDK_NGX_DLSS_Hint_Render_Preset_*, or 0 to let NGX pick the default for this quality
        /// level. Note the Super Resolution preset letters are a different enum from the Ray
        /// Reconstruction ones -- do not pass a value from the wrong header.
        uint32_t renderPreset = 0
    );

    /// Log which nvngx_dlss*.dll is actually mapped into the process, and its file version. The
    /// feature search path is only a hint -- NGX falls back to the executable directory -- so this is
    /// the one reliable way to know which trained network is running.
    static void logLoadedFeatureDll(const char* moduleName);

    /// Release DLSS.
    void releaseDLSS();

    /// Checks if DLSS is initialized.
    bool isDLSSInitialized() const { return mpFeatureSR != nullptr; }

    /// Whether the driver reports each NGX feature as usable. Queried once at init; neither is
    /// fatal on its own, so a machine with Super Resolution but no Ray Reconstruction (or an SDK
    /// without the DLSS-D DLL) still runs the SR path normally.
    bool isSRAvailable() const { return mSRAvailable; }
    bool isRRAvailable() const { return mRRAvailable; }

#if FALCOR_HAS_DLSSD
    /// Inputs for one Ray Reconstruction evaluation. A struct rather than more positional
    /// arguments -- DLSS-D takes four guide buffers on top of what Super Resolution needs, and
    /// evaluateDLSS()'s ten-argument list is already at the limit of what is readable.
    struct DLSSDEvalInputs
    {
        Texture* color = nullptr;
        Texture* output = nullptr;
        Texture* depth = nullptr;          ///< Linear view Z (Depth_Type_Linear).
        Texture* motionVectors = nullptr;
        Texture* diffuseAlbedo = nullptr;
        Texture* specularAlbedo = nullptr;
        Texture* normals = nullptr;
        Texture* roughness = nullptr;      ///< Separate texture (Roughness_Mode_Unpacked).
        Texture* exposure = nullptr;       ///< Optional.
    };

    /// Initialize DLSS Ray Reconstruction. Throws if unable to initialize.
    void initializeDLSSD(
        RenderContext* pRenderContext,
        uint2 maxRenderSize,
        uint2 displayOutSize,
        bool isContentHDR,
        NVSDK_NGX_PerfQuality_Value perfQuality = NVSDK_NGX_PerfQuality_Value_MaxQuality,
        uint32_t renderPreset = 0
    );

    /// Release DLSS Ray Reconstruction.
    void releaseDLSSD();

    bool isDLSSDInitialized() const { return mpFeatureRR != nullptr; }

    /// Evaluate DLSS Ray Reconstruction.
    ///
    /// worldToView/viewToClip are optional but worth supplying: RR uses them for reprojection that
    /// depth and motion vectors alone cannot express. frameTimeDeltaMs lets it scale how much it
    /// denoises with the speed implied by the motion-vector magnitudes.
    bool evaluateDLSSD(
        RenderContext* pRenderContext,
        const DLSSDEvalInputs& inputs,
        bool resetAccumulation = false,
        float2 jitterOffset = {0.f, 0.f},
        float2 motionVectorScale = {1.f, 1.f},
        const float4x4* pWorldToView = nullptr,
        const float4x4* pViewToClip = nullptr,
        float frameTimeDeltaMs = 0.f
    ) const;
#endif

    //// Evaluate DLSS.
    bool evaluateDLSS(
        RenderContext* pRenderContext,
        Texture* pUnresolvedColor,
        Texture* pResolvedColor,
        Texture* pMotionVectors,
        Texture* pDepth,
        Texture* pExposure,
        bool resetAccumulation = false,
        float sharpness = 0.0f,
        float2 jitterOffset = {0.f, 0.f},
        float2 motionVectorScale = {1.f, 1.f}
    ) const;

private:
    void initializeNGX(const std::filesystem::path& applicationDataPath, const std::filesystem::path& featureSearchPath);
    void shutdownNGX();

    ref<Device> mpDevice;
    bool mInitialized = false;

    NVSDK_NGX_Parameter* mpParameters = nullptr;

    // Separate handles per feature. Sharing one would break silently: shutdownNGX() releases
    // unconditionally and each evaluate() early-returns on null, so whichever feature was created
    // last would win and the other would quietly stop running.
    NVSDK_NGX_Handle* mpFeatureSR = nullptr;
    NVSDK_NGX_Handle* mpFeatureRR = nullptr;

    bool mSRAvailable = false;
    bool mRRAvailable = false;
};
} // namespace Falcor
