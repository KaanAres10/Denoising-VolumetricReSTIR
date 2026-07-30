/***************************************************************************
 # Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
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
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
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
#include "RenderGraph/RenderPass.h"
#include "RenderGraph/RenderPassHelpers.h" // RenderPassHelpers::IOSize for the render-scale property
#include "Utils/SampleGenerators/CPUSampleGenerator.h"
#include "Utils/Sampling/SampleGenerator.h"
#include "Rendering/Lights/EnvMapSampler.h"
#include "Rendering/Lights/LightBVHSampler.h"
#include "Rendering/Lights/EmissivePowerSampler.h"
#include "Rendering/Lights/EmissiveUniformSampler.h"
#include "Rendering/Lights/EmissiveLightSampler.h"
#include "HostDeviceSharedDefinitions.slangh"
#include "Utils/Debug/PixelDebug.h"
#include "HostDeviceSharedConstants.slang"

using namespace Falcor;

class VolumetricReSTIR : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(VolumetricReSTIR, "VolumetricReSTIR", "Volumetric ReSTIR render pass.");

    static ref<VolumetricReSTIR> create(ref<Device> pDevice, const Properties& props)
    {
        return make_ref<VolumetricReSTIR>(pDevice, props);
    }

    VolumetricReSTIR(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pContext, const CompileData& compileData) override {}
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;
    virtual void setScene(RenderContext* pRenderContext, const ref<Scene>& pScene) override;
    virtual bool onMouseEvent(const MouseEvent& mouseEvent) override;
    virtual bool onKeyEvent(const KeyboardEvent& keyEvent) override;

    /** Resolution the pass renders at this frame. Equals the swapchain size unless a render scale
        is set via the outputSize property, in which case it is the size of the bound outputs. */
    uint2 getRenderDims(const RenderData& renderData) const;
    /// Display size -> render size under the upscaling switch. See mUpscaling.
    uint2 upscaledRenderSize(const uint2& displayDims) const;
    virtual void setProperties(const Properties& props) override;

private:
    void updateSceneDefines(ref<ComputePass>& pPass, const ref<Scene>& pScene);
    bool updateLights(RenderContext* pRenderContext);
    void beginFrame(RenderContext* pRenderContext, const RenderData& renderData);
    void toggleCameraAnimation();
    void overrideVolumeDesc();
    void moveCameraRight(float distance, float3 anchorPosition);
    void _forwardCameraInterval(float distance, float3 anchorPosition);
    void resetCamera(bool useLastCameraPosition);

    ref<Sampler> mpSampler;
    ref<Sampler> mpPointSampler;

    ref<Scene> mpScene;

    int mFrameCount = 0;

    ref<SampleGenerator>                mpSampleGenerator;              ///< GPU sample generator.
    std::unique_ptr<EnvMapSampler>      mpEnvMapSampler;                ///< Environment map sampler or nullptr if disabled.
    std::unique_ptr<EmissiveLightSampler> mpEmissiveSampler;

    int mEmissiveSamplerTypeId = 2;
    EmissiveLightSamplerType mEmissiveSamplerType = EmissiveLightSamplerType::Power;
    LightBVHSampler::Options            mLightBVHSamplerOptions;        ///< Current options for the light BVH sampler.

    std::unique_ptr<PixelDebug>         mpPixelDebug;                   ///< Utility class for pixel debugging (print in shaders).

    std::vector<ref<Texture>> mTemporalSampleBuffers;
    ref<Buffer> mPerPixelReservoirBuffer[2];
    ref<Buffer> mTemporalReservoirBuffer;
    ref<Buffer> mPerPixelExtraBounceReservoirBuffer[2];
    ref<Buffer> mTemporalExtraBounceReservoirBuffer;
    ref<Buffer> mReservoirFeatureBuffer;
    ref<Buffer> mTemporalReservoirFeatureBuffer;
    ref<Buffer> mVBuffer;
    ref<Buffer> mTemporalVBuffer;

    // for debug purpose
    ref<Texture> mAccumulateBuffer;
    ref<Texture> mPerPixelColorBuffer[2];
    ref<Texture> mOutputBackupBuffer;

    ref<ComputePass> mpTraceRaysPass;
    ref<ComputePass> mTemporalReusePass;
    ref<ComputePass> mSpatialReusePass;
    ref<ComputePass> mGenerateFeaturePass;
    ref<ComputePass> mCopyReservoirPass;
    ref<ComputePass> mFinalShadingPass;
    ref<ComputePass> mComputeAvgDensityPass;


	bool mFreezeFrame = false;
    bool mFreezeAnimation = false;

    /////////////////////
    /// Global controls
    /////////////////////
    public:

    int mLastMaxBounces = 1;
    bool mLastVertexReuse = false;

    struct VolumetricReSTIRParams
    {
        int mMaxBounces = 1;

        bool mEnableTemporalReuse = true;
        bool mEnableSpatialReuse = true;
        bool mVertexReuse = false;
        int mVertexReuseStartBounce = 1;

        bool mUseReference = false;

        bool mUseEnvironmentLights = true;
        bool mUseAnalyticLights = false;
        bool mUseEmissiveLights = false;

        int mBaselineSamplePerPixel = 1;

        // Alternatives

        bool mVisualizeTotalTransmittance = false;

        bool mUseSurfaceScene = false;
        bool mUsePrevVolumeForReproj = true;

        /////////////////////
        /// Initial Sampling
        /////////////////////
        int mInitialBaseMipLevel = 1;
        int mInitialM = 4;
        int mInitialLightSamples = 1;
        int mInitialLightingMipLevel = 2;
        bool mInitialVisibilityUseLinearSampler = false;
        bool mInitialLightingUseLinearSampler = true;

        uint32_t mInitialLightingTrackingMethod = kRayMarching;
        float mInitialVisibilityTStepScale = 1.f;
        float mInitialLightingTStepScale = 2.f;
        bool mInitialUseRussianRoulette = true;
        bool mInitialUseCoarserGridForIndirectBounce = true;

        /////////////////////
        /// Temporal Reuse
        /////////////////////
        float mTemporalReuseMThreshold = 4.f;
        uint32_t mTemporalReprojectionMode = kReprojectionLinear;
        uint32_t mTemporalMISMethod = kMISTalbot;
        int mTemporalReprojectionMipLevel = 1;

        /////////////////////
        /// Spatial Reuse
        /////////////////////
        int mSpatialReuseRounds = 1;
        int mSpatialVisibilityMipLevel = 1;
        int mSpatialLightingMipLevel = 1;
        bool mSpatialVisibilityUseLinearSampler = true;
        bool mSpatialLightingUseLinearSampler = true;
        float mSpatialVisibilityTStepScale = 1.f;
        float mSpatialLightingTStepScale = 1.f;
        uint32_t mSpatialVisibilityTrackingMethod = kRayMarching;
        uint32_t mSpatialLightingTrackingMethod = kRayMarching;
        uint32_t mRandomSamplerType = kR2;
        float mSampleRadius = 10.f;

        int mSpatialSampleCount = 4;
        bool mEnableVisibilitySimilarityRejection = false;

        uint32_t mSpatialMISMethod = kMISTalbot;

        /////////////////////
        /// Final Shading
        /////////////////////
        int mFinalLightSamples = 1;
        int mFinalVisibilitySamples = 1;
        uint32_t mFinalVisibilityTrackingMethod = kAnalyticTracking;
        uint32_t mFinalLightTrackingMethod = kAnalyticTracking;
        uint32_t mFinalRandomSamplerType = kR2;
        float mFinalTStepScale = 0.2f;

        template<typename Archive>
        void serialize(Archive& ar)
        {
            ar("mMaxBounces", mMaxBounces);
            ar("mEnableTemporalReuse", mEnableTemporalReuse);
            ar("mEnableSpatialReuse", mEnableSpatialReuse);
            ar("mVertexReuse", mVertexReuse);
            ar("mVertexReuseStartBounce", mVertexReuseStartBounce);
            ar("mUseReference", mUseReference);
            ar("mUseEnvironmentLights", mUseEnvironmentLights);
            ar("mUseAnalyticLights", mUseAnalyticLights);
            ar("mUseEmissiveLights", mUseEmissiveLights);
            ar("mBaselineSamplePerPixel", mBaselineSamplePerPixel);
            ar("mVisualizeTotalTransmittance", mVisualizeTotalTransmittance);
            ar("mUseSurfaceScene", mUseSurfaceScene);
            ar("mUsePrevVolumeForReproj", mUsePrevVolumeForReproj);
            ar("mInitialBaseMipLevel", mInitialBaseMipLevel);
            ar("mInitialM", mInitialM);
            ar("mInitialLightSamples", mInitialLightSamples);
            ar("mInitialLightingMipLevel", mInitialLightingMipLevel);
            ar("mInitialVisibilityUseLinearSampler", mInitialVisibilityUseLinearSampler);
            ar("mInitialLightingUseLinearSampler", mInitialLightingUseLinearSampler);
            ar("mInitialLightingTrackingMethod", mInitialLightingTrackingMethod);
            ar("mInitialVisibilityTStepScale", mInitialVisibilityTStepScale);
            ar("mInitialLightingTStepScale", mInitialLightingTStepScale);
            ar("mInitialUseRussianRoulette", mInitialUseRussianRoulette);
            ar("mInitialUseCoarserGridForIndirectBounce", mInitialUseCoarserGridForIndirectBounce);
            ar("mTemporalReuseMThreshold", mTemporalReuseMThreshold);
            ar("mTemporalReprojectionMode", mTemporalReprojectionMode);
            ar("mTemporalMISMethod", mTemporalMISMethod);
            ar("mTemporalReprojectionMipLevel", mTemporalReprojectionMipLevel);
            ar("mSpatialReuseRounds", mSpatialReuseRounds);
            ar("mSpatialVisibilityMipLevel", mSpatialVisibilityMipLevel);
            ar("mSpatialLightingMipLevel", mSpatialLightingMipLevel);
            ar("mSpatialVisibilityUseLinearSampler", mSpatialVisibilityUseLinearSampler);
            ar("mSpatialLightingUseLinearSampler", mSpatialLightingUseLinearSampler);
            ar("mSpatialVisibilityTStepScale", mSpatialVisibilityTStepScale);
            ar("mSpatialLightingTStepScale", mSpatialLightingTStepScale);
            ar("mSpatialVisibilityTrackingMethod", mSpatialVisibilityTrackingMethod);
            ar("mSpatialLightingTrackingMethod", mSpatialLightingTrackingMethod);
            ar("mRandomSamplerType", mRandomSamplerType);
            ar("mSampleRadius", mSampleRadius);
            ar("mSpatialSampleCount", mSpatialSampleCount);
            ar("mEnableVisibilitySimilarityRejection", mEnableVisibilitySimilarityRejection);
            ar("mSpatialMISMethod", mSpatialMISMethod);
            ar("mFinalLightSamples", mFinalLightSamples);
            ar("mFinalVisibilitySamples", mFinalVisibilitySamples);
            ar("mFinalVisibilityTrackingMethod", mFinalVisibilityTrackingMethod);
            ar("mFinalLightTrackingMethod", mFinalLightTrackingMethod);
            ar("mFinalRandomSamplerType", mFinalRandomSamplerType);
            ar("mFinalTStepScale", mFinalTStepScale);
        }
    } mParams;

    private:

    bool hasExternalDict = false;

    /////////////////////
    /// Internal Variables
    /////////////////////
    int mTemporalSampleAccumulated = 0;

    float4x4 mPrevViewMat;
    float4x4 mPrevProjMat;
    float3 mPrevCameraU, mPrevCameraV, mPrevCameraW, mPrevCameraPosW;
    float2 mPrevJitter = { 0.f, 0.f };  ///< Jitter the previous frame was rendered with (see gPrevJitter).
    /// Feed mPrevJitter to the shader. Off reproduces the pre-fix behaviour (previous-frame rays
    /// reconstructed WITHOUT jitter), which is only useful for measuring what the fix is worth.
    bool mApplyPrevJitter = true;

    // TemporalReuse.cs.slang reprojects with the Falcor 4.x convention `mul(v, M)`, which under
    // Falcor 8's row-major Slang layout (ProgramManager.cpp: MatrixLayoutRow, and ParameterBlock
    // uploads matrices verbatim) evaluates M^T * v. Falcor 8's own matrices are built for
    // `mul(M, v)` (cf. GBufferRT.slang), so they must be transposed on upload -- the same fix
    // SceneGVDB.cpp applies to the GVDB matrices. Exposed as a property purely so the old
    // behaviour can be A/B'd; a wrong reprojection costs variance, not correctness, because the
    // Talbot MIS weights are re-derived from whichever tap is selected.
    bool mTransposePrevMatrices = true;

    /////////////////////
    /// Guide buffers for temporal upscalers (DLSS). All default OFF, so existing scripts and the
    /// estimator are bit-identical unless deliberately enabled. The outputs are optional, so when
    /// unconnected they are not even allocated.
    /////////////////////
    // Motion-vector source. Legacy = the original stochastic writer in TemporalReuse (integer-pixel
    // quantised, only written when temporal reuse runs); Deterministic = the sub-pixel, per-frame
    // writer in GenerateFeatures, which is what a temporal upscaler needs.
    enum class MotionVecMode { Off = 0, Legacy = 1, Deterministic = 2 };
    MotionVecMode mMotionVecMode = MotionVecMode::Off;
    bool mOutputDepth = false;
    /// Export medium coverage + a stand-in medium normal, for blending volumetric guides into
    /// DLSS Ray Reconstruction. Off by default; unconnected outputs are never allocated.
    bool mOutputVolumeGuides = false;

    // Render scale. 'Default' reproduces the previous behaviour exactly (outputs sized to the
    // swapchain), so existing scripts are unaffected. Setting this below display resolution is what
    // makes a temporal upscaler actually save time: ReSTIR runs on fewer pixels and DLSS restores
    // the display resolution. Mirrors GBufferBase's outputSize/fixedOutputSize pattern.
    RenderPassHelpers::IOSize mOutputSizeSelection = RenderPassHelpers::IOSize::Default;
    uint2 mFixedOutputSize = { 512, 512 };

    /// The upscaling switch. On => render at mUpscaleRatio of the DISPLAY and let a downstream DLSS
    /// pass reconstruct; off => whatever mOutputSizeSelection says (Default = native). Expressing it
    /// as a ratio of the display rather than a fixed size means the aspect ratio is preserved by
    /// construction -- the camera aspect comes from the swapchain, so a mismatched fixed size
    /// stretches the image, and that footgun simply cannot be reached through this control.
    /// Mutable so upscaledRenderSize() (const, called from reflect()) can adopt the graph-wide scale.
    mutable bool mUpscaling = false;
    /// Last graph-wide render-scale generation adopted. See Falcor::getRenderScale().
    mutable uint32_t mRenderScaleGen = 0;
    /// 0.5 / 0.58 / 0.667 correspond to DLSS MaxPerf / Balanced / MaxQuality. Keep this in step with
    /// the downstream pass's profile: DLSS queries its own optimal size, and a mismatch means it
    /// reconstructs from a different ratio than it was tuned for.
    mutable float mUpscaleRatio = 0.58f;
    /// Last render resolution actually used, for display in the UI.
    uint2 mLastRenderDims = {0, 0};
    /// Last swapchain/display size, so the UI presets are a fraction of the DISPLAY rather than of
    /// the current render size (which would compound on every click).
    uint2 mLastDisplayDims = {0, 0};

    // Camera jitter. A temporal upscaler needs a varying subpixel offset to resolve detail below one
    // input pixel. Camera::setPatternGenerator is global and last-writer-wins, so this pass must own
    // it once a render scale is in play (the generator has to be scaled by 1/renderDim, not
    // 1/displayDim) -- a GBuffer left in the graph would silently fight it.
    //
    // DEFAULT IS Center == NO JITTER, which resets the camera jitter to (0,0) and therefore leaves
    // primary rays bit-identical to every existing script. See the README note: enabling jitter
    // while temporal reuse is on is the one setting here that is NOT estimator-neutral.
    enum class SamplePattern { Center = 0, Halton = 1, Stratified = 2, DirectX = 3 };
    SamplePattern mSamplePattern = SamplePattern::Center;
    uint32_t mSampleCount = 32;
    ref<CPUSampleGenerator> mpJitterGenerator;   ///< CPU pattern for camera jitter (distinct from the GPU mpSampleGenerator above).
    uint2 mLastJitterFrameDim = { 0, 0 };

    void updateSamplePattern();
    void updateJitter(const uint2& frameDim);
    // false = linear view Z (matches GBufferRT.linearZ, the encoding PathTracerNRD.py feeds DLSS);
    // true = NDC depth. Runtime-switchable because DLSSPass advertises NDC to NGX but linear Z is
    // what the shipped graph actually uses.
    bool mDepthAsNDC = false;

    // camera animation
    float3 mBackedupCameraPosition;
    float3 mBackedupCameraTarget;
    float3 mBackedupCameraPosition2;
    float3 mInitialCameraPosition;
    float3 mInitialCameraTarget;
    int mCameraFramesMoved = 0;
    float mCameraMoveScale = 0.3f;
    int mCameraFrameInterval = 50;
    float mCameraForwardScale = 1.f;
    uint32_t mCameraAnimationMode = 0;
    int mCameraPauseInterval = 150;
    int mCameraShakeRoundsBeforePause = 3;
    int mCameraShakeTotalRounds = 1;

    // rotating around model
    int mCameraRotationFrames = 360;
    float mCameraRotationSpeed = 1; // degrees per frame
    float mCameraRotationDistance = 0; // if <= 0, use initial distance to the center of the volume
    bool mEnableCameraRotation = false;

    bool mOptionsChanged = true;
    bool mRandomizeFrameSpeed = false;

    // light animation
    bool mLastAnimateEnvLight = false;
    bool mAnimateEnvLight = false;
    double mAnimationStartTime = 0;
    int mAnimationFrameCount = 0;
    int mAnimationFreezedFrame = -1;
    float3 mSavedEnvMapRotation;

    // extra volume desc control
    float volumeAnisotropyExtraControl = -1.f;
	float volumeDensityScaleExtraControl = -1.f;
    float volumeAlbedoExtraControl = -1.f;

    float mEnvLightRotationSpeed = 0.1f;

    // Volume animation
    bool mSavedVDBAnimationState = false;

    int mVolumeAnimationSelectedFrameId = -1; // this is for freezing animation

    bool mOutputMotionVec = false; // enable when using Optix 7.3

    bool mRequestRecreateVarsForEmissiveSampler = false;
    DefineList mDefaultDefines;

    std::vector<float3> mPointLightUnitSpherePos;

    // Scripting: serialize pass options to/from a Properties object.
    void parseProperties(const Properties& props);
};
