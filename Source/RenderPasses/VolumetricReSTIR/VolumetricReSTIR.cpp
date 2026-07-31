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
#include "VolumetricReSTIR.h"
#include "RenderGraph/RenderPassHelpers.h"
#include "RenderGraph/RenderPassStandardFlags.h"
#include "Utils/SampleGenerators/HaltonSamplePattern.h"
#include "Utils/SampleGenerators/StratifiedSamplePattern.h"
#include "Utils/SampleGenerators/DxSamplePattern.h"
#include "Utils.h"
#include <random>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace
{
    const std::string kShaderDirectory = "RenderPasses/VolumetricReSTIR/";
    const std::string kAccumulatedColorOutput = "accumulated_color";
    const std::string kMotionVec = "mvec";
    const std::string kLinearZ = "linearZ";
    const std::string kMediumAlpha = "mediumAlpha";
    const std::string kMediumNormal = "mediumNormal";
    const std::string kScatterDistance = "scatterDistance";
    const std::string kLightDir = "lightDir";
    const std::string kOpticalThickness = "opticalThickness";
    const std::string kVolumeVelocity = "volumeVelocity";
    const std::string kScatterDensity = "scatterDensity";

    const Falcor::ChannelList kOutputChannels =
    {
        // [8.0 port] accumulated_color is written as a UAV by FinalShading, so it needs an explicit
        // UAV-capable format (RGBA32Float). Without a format it defaults to the swapchain's
        // BGRA8UnormSrgb, which does not support UnorderedAccess.
        { kAccumulatedColorOutput,     "gOutputFrame",    "accumulated output color (linear)", true /* optional */, ResourceFormat::RGBA32Float      },
        { kMotionVec,     "gMotionVec",    "motion vector", true /* optional */, ResourceFormat::RG32Float      },
        // Guide buffer for temporal upscalers (DLSS). Matches GBufferRT's "linearZ" layout: .x is
        // linear view Z (or NDC depth when mDepthAsNDC), .y is an unused slope channel.
        { kLinearZ,       "gLinearZ",      "linear view-space Z of the expected scatter point", true /* optional */, ResourceFormat::RG32Float      },
        // Volumetric guides for DLSS Ray Reconstruction. mediumAlpha is 1 - transmittance, i.e. how
        // much of the pixel the participating medium accounts for; mediumNormal is a stand-in
        // orientation for a medium that has no surface. Both optional: unconnected costs nothing.
        { kMediumAlpha,   "gMediumAlpha",  "medium coverage (1 - transmittance)", true /* optional */, ResourceFormat::R16Float       },
        { kMediumNormal,  "gMediumNormal", "medium guide normal (world space)", true /* optional */, ResourceFormat::RGBA16Float    },
        // Expected scattering distance along the primary ray, in world units, or -1 where the ray
        // never met the medium. NRD wants a hit distance to size its filter kernel. R32Float, not
        // R16: this is a world-space distance, unlike mediumAlpha's [0,1] coverage. Kept as a raw
        // ray distance rather than the projected view Z that linearZ carries, and written before
        // linearZ's far-plane fallback so the -1 "no medium" sentinel survives.
        { kScatterDistance, "gScatterDistance", "expected scatter distance along the primary ray (-1 = no medium)", true /* optional */, ResourceFormat::R32Float },
        // Written by FinalShading, not GenerateFeatures: it is derived from the FINAL reservoir, which
        // only exists after reuse. .w = 0 marks a direction that must not be trusted (no sample, or a
        // volume with emission, where Reservoir::lightID is overloaded -- see FinalShading.cs.slang).
        // Required by NRD v4's SH mode.
        { kLightDir,      "gLightDir",     "dominant light direction at the first scatter vertex (w=1 valid)", true /* optional */, ResourceFormat::RGBA16Float },
        // Optical thickness tau = -log(transmittance) along the primary ray. One of the volumetric
        // features Zhang et al. select over; free here because the march already accumulates the
        // exponent. R32Float, not R16: it is unbounded in principle, though the march's
        // transmittance early-out clamps it near 4.6 in practice.
        { kOpticalThickness, "gOpticalThickness", "optical thickness along the primary ray", true /* optional */, ResourceFormat::R32Float },
        // Velocity of the medium at the scatter point: xyz = unit direction, w = magnitude in world
        // units per frame. Zhang et al. list direction and magnitude as two separate features, and
        // keeping them apart matters here -- magnitude is what a temporal denoiser needs to decide
        // where reprojection should be distrusted. RGBA16Float, not a packed unsigned format: the
        // direction is signed.
        { kVolumeVelocity, "gVolumeVelocity", "medium velocity at the scatter point (xyz = direction, w = magnitude)", true /* optional */, ResourceFormat::RGBA16Float },
        // Density at the scatter point. The one LOCAL volumetric quantity here -- transmittance,
        // optical thickness and scatter distance are all integrals along the ray, which average away
        // exactly the interior structure the denoiser is destroying.
        { kScatterDensity, "gScatterDensity", "medium density at the expected scatter point", true /* optional */, ResourceFormat::R32Float }
    };

    const Gui::DropdownList kEmissiveSamplerList =
    {
        { (uint32_t)EmissiveLightSamplerType::Uniform, "Uniform" },
        { (uint32_t)EmissiveLightSamplerType::LightBVH, "LightBVH" },
        { (uint32_t)EmissiveLightSamplerType::Power, "Power" }
    };

};


extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, VolumetricReSTIR>();
}

VolumetricReSTIR::VolumetricReSTIR(ref<Device> pDevice, const Properties& props)
    : RenderPass(pDevice)
{
    mDefaultDefines.add("SAMPLE_GENERATOR_TYPE", "SAMPLE_GENERATOR_UNIFORM");

    mpSampleGenerator = SampleGenerator::create(pDevice, SAMPLE_GENERATOR_UNIFORM);

    Sampler::Desc samplerDesc;
    samplerDesc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Linear);
    samplerDesc.setBorderColor(float4(0.f));
    samplerDesc.setAddressingMode(TextureAddressingMode::Border, TextureAddressingMode::Border, TextureAddressingMode::Border);
    mpSampler = pDevice->createSampler(samplerDesc);

    samplerDesc.setFilterMode(TextureFilteringMode::Point, TextureFilteringMode::Point, TextureFilteringMode::Point);
    mpPointSampler = pDevice->createSampler(samplerDesc);

	if (!props.empty()) hasExternalDict = true;

	parseProperties(props);

    if (mEmissiveSamplerTypeId == 0)
    {
        mEmissiveSamplerType = EmissiveLightSamplerType::Uniform;
    }
    else if (mEmissiveSamplerTypeId == 1)
    {
        mEmissiveSamplerType = EmissiveLightSamplerType::LightBVH;
    }
    else
    {
        mEmissiveSamplerType = EmissiveLightSamplerType::Power;
    }

    // TODO: allow overriding these options

    if (mParams.mUseSurfaceScene)
    {
        mDefaultDefines.add("SURFACE_SCENE");
        mDefaultDefines.add("VBUFFERDECLARE", "VBufferItem vItem,");
        mDefaultDefines.add("VBUFFERITEM", "vItem,");
    }
    else
    {
        mDefaultDefines.add("VBUFFERDECLARE", "");
        mDefaultDefines.add("VBUFFERITEM", "");
    }

    if (mParams.mVertexReuse)
    {
        mDefaultDefines.add("VERTEX_REUSE");
        mDefaultDefines.add("REUSETYPE", "inout");
    }
    else
    {
        mDefaultDefines.add("REUSETYPE", "");
    }

    mDefaultDefines.add("_EMISSIVE_LIGHT_SAMPLER_TYPE", "0"); // uniform
    mDefaultDefines.add("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));

    mLastMaxBounces = mParams.mMaxBounces;

    mpTraceRaysPass = createSimpleComputePass(pDevice, kShaderDirectory + "TraceRays.cs.slang", "main", mDefaultDefines);
    mSpatialReusePass = createSimpleComputePass(pDevice, kShaderDirectory + "SpatialReuse.cs.slang", "main", mDefaultDefines);
    mTemporalReusePass = createSimpleComputePass(pDevice, kShaderDirectory + "TemporalReuse.cs.slang", "main", mDefaultDefines);
    mGenerateFeaturePass = createSimpleComputePass(pDevice, kShaderDirectory + "GenerateFeatures.cs.slang", "main", mDefaultDefines);
    mCopyReservoirPass = createSimpleComputePass(pDevice, kShaderDirectory + "CopyReservoirs.cs.slang", "main", mDefaultDefines);
    mFinalShadingPass = createSimpleComputePass(pDevice, kShaderDirectory + "FinalShading.cs.slang", "main", mDefaultDefines);
    mpPixelDebug = std::make_unique<PixelDebug>(pDevice);
}

void VolumetricReSTIR::parseProperties(const Properties& props)
{
    props.getTo("mParams", mParams);
    props.getTo("mCameraMoveScale", mCameraMoveScale);
    props.getTo("mCameraForwardScale", mCameraForwardScale);
    props.getTo("mCameraFrameInterval", mCameraFrameInterval);
    props.getTo("mCameraPauseInterval", mCameraPauseInterval);
    props.getTo("mCameraShakeTotalRounds", mCameraShakeTotalRounds);
    props.getTo("mCameraShakeRoundsBeforePause", mCameraShakeRoundsBeforePause);
    props.getTo("mCameraAnimationMode", mCameraAnimationMode);
    props.getTo("mAnimateEnvLight", mAnimateEnvLight);
    props.getTo("mAnimationFreezedFrame", mAnimationFreezedFrame);
    props.getTo("mEnvLightRotationSpeed", mEnvLightRotationSpeed);
    props.getTo("mFreezeFrame", mFreezeFrame);
    props.getTo("mVolumeAnimationSelectedFrameId", mVolumeAnimationSelectedFrameId);
    props.getTo("mEmissiveSamplerTypeId", mEmissiveSamplerTypeId);
    props.getTo("volumeDensityScaleExtraControl", volumeDensityScaleExtraControl);
    props.getTo("volumeAlbedoExtraControl", volumeAlbedoExtraControl);
    props.getTo("volumeAnisotropyExtraControl", volumeAnisotropyExtraControl);
    props.getTo("mOutputMotionVec", mOutputMotionVec);
    props.getTo("mTransposePrevMatrices", mTransposePrevMatrices);
    props.getTo("mApplyPrevJitter", mApplyPrevJitter);

    // Back-compat: the old boolean selects the legacy stochastic writer.
    if (mOutputMotionVec && mMotionVecMode == MotionVecMode::Off) mMotionVecMode = MotionVecMode::Legacy;
    {
        std::string mode;
        if (props.getTo("mMotionVecMode", mode))
        {
            if (mode == "Off") mMotionVecMode = MotionVecMode::Off;
            else if (mode == "Legacy") mMotionVecMode = MotionVecMode::Legacy;
            else if (mode == "Deterministic") mMotionVecMode = MotionVecMode::Deterministic;
            else logWarning("VolumetricReSTIR: unknown mMotionVecMode '{}' (expected Off|Legacy|Deterministic)", mode);
        }
    }
    props.getTo("mOutputDepth", mOutputDepth);
    props.getTo("mOutputVolumeGuides", mOutputVolumeGuides);
    props.getTo("mDepthAsNDC", mDepthAsNDC);
    {
        std::string mode;
        if (props.getTo("mVolumeNormalMode", mode))
        {
            if (mode == "Camera") mVolumeNormalMode = VolumeNormalMode::Camera;
            else if (mode == "Gradient") mVolumeNormalMode = VolumeNormalMode::Gradient;
            else logWarning("VolumetricReSTIR: unknown mVolumeNormalMode '{}' (expected Camera|Gradient)", mode);
        }
    }

    props.getTo("outputSize", mOutputSizeSelection);
    props.getTo("fixedOutputSize", mFixedOutputSize);
    props.getTo("upscale", mUpscaling);
    props.getTo("upscaleRatio", mUpscaleRatio);
    {
        std::string pattern;
        if (props.getTo("samplePattern", pattern))
        {
            if (pattern == "Center") mSamplePattern = SamplePattern::Center;
            else if (pattern == "Halton") mSamplePattern = SamplePattern::Halton;
            else if (pattern == "Stratified") mSamplePattern = SamplePattern::Stratified;
            else if (pattern == "DirectX") mSamplePattern = SamplePattern::DirectX;
            else logWarning("VolumetricReSTIR: unknown samplePattern '{}' (expected Center|Halton|Stratified|DirectX)", pattern);
        }
    }
    props.getTo("sampleCount", mSampleCount);
    updateSamplePattern();
}

Properties VolumetricReSTIR::getProperties() const
{
    Properties props;
    props.set("mParams", mParams);
    props.set("mCameraMoveScale", mCameraMoveScale);
    props.set("mCameraForwardScale", mCameraForwardScale);
    props.set("mCameraFrameInterval", mCameraFrameInterval);
    props.set("mCameraPauseInterval", mCameraPauseInterval);
    props.set("mCameraShakeTotalRounds", mCameraShakeTotalRounds);
    props.set("mCameraShakeRoundsBeforePause", mCameraShakeRoundsBeforePause);
    props.set("mCameraAnimationMode", mCameraAnimationMode);
    props.set("mAnimateEnvLight", mAnimateEnvLight);
    props.set("mAnimationFreezedFrame", mAnimationFreezedFrame);
    props.set("mEnvLightRotationSpeed", mEnvLightRotationSpeed);
    props.set("mFreezeFrame", mFreezeFrame);
    props.set("mVolumeAnimationSelectedFrameId", mVolumeAnimationSelectedFrameId);
    props.set("mEmissiveSamplerTypeId", mEmissiveSamplerTypeId);
    props.set("volumeDensityScaleExtraControl", volumeDensityScaleExtraControl);
    props.set("volumeAlbedoExtraControl", volumeAlbedoExtraControl);
    props.set("volumeAnisotropyExtraControl", volumeAnisotropyExtraControl);
    props.set("mOutputMotionVec", mOutputMotionVec);
    props.set("mTransposePrevMatrices", mTransposePrevMatrices);
    props.set("mApplyPrevJitter", mApplyPrevJitter);
    props.set("mMotionVecMode", mMotionVecMode == MotionVecMode::Deterministic ? "Deterministic"
                              : mMotionVecMode == MotionVecMode::Legacy        ? "Legacy"
                                                                               : "Off");
    props.set("mOutputDepth", mOutputDepth);
    props.set("mOutputVolumeGuides", mOutputVolumeGuides);
    props.set("mDepthAsNDC", mDepthAsNDC);
    props.set("mVolumeNormalMode", mVolumeNormalMode == VolumeNormalMode::Gradient ? "Gradient" : "Camera");
    props.set("outputSize", mOutputSizeSelection);
    if (mOutputSizeSelection == RenderPassHelpers::IOSize::Fixed) props.set("fixedOutputSize", mFixedOutputSize);
    props.set("upscale", mUpscaling);
    if (mUpscaling) props.set("upscaleRatio", mUpscaleRatio);
    props.set("samplePattern", mSamplePattern == SamplePattern::Halton     ? "Halton"
                             : mSamplePattern == SamplePattern::Stratified ? "Stratified"
                             : mSamplePattern == SamplePattern::DirectX    ? "DirectX"
                                                                          : "Center");
    props.set("sampleCount", mSampleCount);
    return props;
}

RenderPassReflection VolumetricReSTIR::reflect(const CompileData& compileData)
{
    // Define the required resources here
    RenderPassReflection reflector;
    // Render scale: 'Default' resolves to compileData.defaultTexDims (the swapchain), reproducing
    // the previous unsized behaviour exactly. Anything smaller is what buys time back for sampling.
    // The upscaling switch overrides the size selection: defaultTexDims IS the display size here, so
    // the ratio resolves against the real swapchain and follows it across a window resize for free.
    const uint2 sz = mUpscaling ? upscaledRenderSize(compileData.defaultTexDims)
                                : RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mFixedOutputSize, compileData.defaultTexDims);
    addRenderPassOutputs(reflector, kOutputChannels, ResourceBindFlags::UnorderedAccess, sz);
    return reflector;
}

void VolumetricReSTIR::updateSamplePattern()
{
    // Mirrors GBufferBase::createSamplePattern. Center => no generator => Camera::setPatternGenerator
    // resets jitter to (0,0), which is the default and keeps the estimator untouched.
    switch (mSamplePattern)
    {
    case SamplePattern::Center:     mpJitterGenerator = nullptr; break;
    case SamplePattern::Halton:     mpJitterGenerator = HaltonSamplePattern::create(mSampleCount); break;
    case SamplePattern::Stratified: mpJitterGenerator = StratifiedSamplePattern::create(mSampleCount); break;
    case SamplePattern::DirectX:    mpJitterGenerator = DxSamplePattern::create(mSampleCount); break;
    }
    mLastJitterFrameDim = uint2(0, 0); // force a re-install on the next frame
}

void VolumetricReSTIR::updateJitter(const uint2& frameDim)
{
    if (!mpScene || any(frameDim == 0u)) return;
    // Only take ownership of the camera jitter when this pass is actually configured to drive it.
    // setPatternGenerator is global and last-writer-wins, so installing a null generator here would
    // silently disable the Halton pattern a GBuffer in the same graph had installed (which is how
    // the Phase 1 DLSS script gets its jitter).
    if (!mpJitterGenerator) return;
    // The generator must be scaled by 1/renderDim: with a render scale the jitter is a subpixel
    // offset of the *render* pixel, not the display pixel.
    if (all(frameDim == mLastJitterFrameDim)) return;
    mLastJitterFrameDim = frameDim;
    mpScene->getCamera()->setPatternGenerator(mpJitterGenerator, 1.f / float2(frameDim));
}

uint2 VolumetricReSTIR::upscaledRenderSize(const uint2& displayDims) const
{
    // See GBufferBase::resolveOutputSize: the render scale is a graph-wide setting, so that toggling
    // it on one pass cannot leave the upscaler with inputs of differing sizes.
    if (getRenderScale().generation != mRenderScaleGen)
    {
        mRenderScaleGen = getRenderScale().generation;
        mUpscaling = getRenderScale().enabled;
        mUpscaleRatio = getRenderScale().ratio;
    }

    // Round each axis down to an even number: NGX wants even render extents, and rounding both axes
    // the same way keeps the aspect within a fraction of a percent of the display's.
    const float r = std::clamp(mUpscaleRatio, 0.25f, 1.f);
    const uint2 sz = uint2(uint32_t(displayDims.x * r) / 2 * 2, uint32_t(displayDims.y * r) / 2 * 2);
    return uint2(std::max(sz.x, 32u), std::max(sz.y, 32u));
}

uint2 VolumetricReSTIR::getRenderDims(const RenderData& renderData) const
{
    // The pass renders at the size of its own (optional) outputs, not the graph default -- those
    // differ whenever a render scale is set. Fall back to the graph default if nothing is bound.
    for (const auto& ch : kOutputChannels)
    {
        if (auto pTex = renderData.getTexture(ch.name)) return uint2(pTex->getWidth(), pTex->getHeight());
    }
    return renderData.getDefaultTextureDims();
}

bool VolumetricReSTIR::updateLights(RenderContext* pRenderContext)
{
    // If no scene is loaded, we disable everything.
    if (!mpScene)
    {
        mpEmissiveSampler = nullptr;
        return false;
    }

    // Request the light collection if emissive lights are enabled.
    if (mParams.mUseEmissiveLights)
    {
        mpScene->getILightCollection(pRenderContext);
    }

    bool lightingChanged = false;
    if (!mpScene->useEmissiveLights())
    {
        mpEmissiveSampler = nullptr;
    }
    else
    {
        // Create emissive light sampler if it doesn't already exist.
        if (mpEmissiveSampler == nullptr)
        {
            switch (mEmissiveSamplerType)
            {
            case EmissiveLightSamplerType::Uniform:
                mpEmissiveSampler = std::make_unique<EmissiveUniformSampler>(pRenderContext, mpScene->getILightCollection(pRenderContext));
                break;
            case EmissiveLightSamplerType::LightBVH:
                mpEmissiveSampler = std::make_unique<LightBVHSampler>(pRenderContext, mpScene->getILightCollection(pRenderContext), mLightBVHSamplerOptions);
                break;
            case EmissiveLightSamplerType::Power:
                mpEmissiveSampler = std::make_unique<EmissivePowerSampler>(pRenderContext, mpScene->getILightCollection(pRenderContext));
                break;
            default:
                logError("Unknown emissive light sampler type");
            }
            if (!mpEmissiveSampler) FALCOR_THROW("Failed to create emissive light sampler");

            // need to recreate vars;
            mRequestRecreateVarsForEmissiveSampler = true;
        }

        // Update the emissive sampler to the current frame.
        FALCOR_ASSERT(mpEmissiveSampler);
        lightingChanged = mpEmissiveSampler->update(pRenderContext, mpScene->getILightCollection(pRenderContext));
    }

    return lightingChanged;
}

void VolumetricReSTIR::beginFrame(RenderContext* pRenderContext, const RenderData& renderData)
{
    // Update lights. Returns true if emissive lights have changed.
    updateLights(pRenderContext);
}

void VolumetricReSTIR::toggleCameraAnimation()
{
    if (mCameraFramesMoved == 0)
    {
        mBackedupCameraPosition = mpScene->getCamera()->getPosition();
        mBackedupCameraTarget = mpScene->getCamera()->getTarget();
        mCameraFramesMoved = 1;
        mSavedVDBAnimationState = mpScene->mPauseVDBAnimation;
    }
    else
    {
        mFreezeFrame = false;
        resetCamera(true);
        mCameraFramesMoved = 0;
        mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
    }
}

void VolumetricReSTIR::overrideVolumeDesc()
{
    if (volumeDensityScaleExtraControl > 0)
    {
        mpScene->getCurrentVolumeDesc().densityScaleFactor = volumeDensityScaleExtraControl;
        mpScene->updateVolumeDesc();
    }

    if (volumeAnisotropyExtraControl > 0)
    {
        mpScene->getCurrentVolumeDesc().PhaseFunctionConstantG = volumeAnisotropyExtraControl;
        mpScene->updateVolumeDesc();
    }

    if (volumeAlbedoExtraControl > 0)
    {
        mpScene->getCurrentVolumeDesc().sigma_s = float3(mpScene->getCurrentVolumeDesc().sigma_t) * volumeAlbedoExtraControl;
        mpScene->getCurrentVolumeDesc().sigma_a = float3(mpScene->getCurrentVolumeDesc().sigma_t) - mpScene->getCurrentVolumeDesc().sigma_s;
        mpScene->updateVolumeDesc();
    }
}

void VolumetricReSTIR::moveCameraRight(float distance, float3 anchorPosition)
{
    float3 viewDir = normalize(mpScene->getCamera()->getTarget() - mpScene->getCamera()->getPosition());
    float3 rightVec = normalize(cross(viewDir, mpScene->getCamera()->getUpVector()));
    float3 newCamPos = anchorPosition + distance * rightVec;
    mpScene->getCamera()->setPosition(newCamPos);
    mpScene->getCamera()->setTarget(newCamPos + viewDir);
}

void VolumetricReSTIR::_forwardCameraInterval(float distance, float3 anchorPosition)
{
    float3 viewDir = normalize(mpScene->getCamera()->getTarget() - anchorPosition);
    float3 forwardCenter = anchorPosition + mCameraForwardScale * viewDir;
    float3 newCamPos = forwardCenter - viewDir * distance;
    mpScene->getCamera()->setPosition(newCamPos);
    mpScene->getCamera()->setTarget(newCamPos + viewDir);
}

void VolumetricReSTIR::resetCamera(bool useLastCameraPosition)
{
    mpScene->getCamera()->setPosition(useLastCameraPosition ? mBackedupCameraPosition : mInitialCameraPosition);
    mpScene->getCamera()->setTarget(useLastCameraPosition ? mBackedupCameraTarget : mInitialCameraTarget);
}

void VolumetricReSTIR::updateSceneDefines(ref<ComputePass>& pPass, const ref<Scene>& pScene)
{
    if (!pScene) return;

    pPass->getProgram()->addDefines(pScene->getSceneDefines());
    pPass->getProgram()->addDefine("_DEFAULT_ALPHA_TEST");
    pPass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
    if (mParams.mUseSurfaceScene)
    {
        pPass->getProgram()->addDefine("SURFACE_SCENE");
        pPass->getProgram()->addDefine("VBUFFERDECLARE", "VBufferItem vItem,");
        pPass->getProgram()->addDefine("VBUFFERITEM", "vItem,");
        // The surface path uses the scene's material system (IMaterial/IMaterialInstance); register the
        // concrete material type conformances so Slang can generate code for them.
        pPass->getProgram()->setTypeConformances(pScene->getTypeConformances());
    }
    else
    {
        pPass->getProgram()->removeDefine("SURFACE_SCENE");
        pPass->getProgram()->addDefine("VBUFFERDECLARE", "");
        pPass->getProgram()->addDefine("VBUFFERITEM", "");
    }
    pPass->setVars(nullptr);
    pScene->bindShaderData(pPass->getRootVar()["gScene"]);
}

void VolumetricReSTIR::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    beginFrame(pRenderContext, renderData);

    mpPixelDebug->beginFrame(pRenderContext, getRenderDims(renderData));

    if (mRequestRecreateVarsForEmissiveSampler)
    {
        mRequestRecreateVarsForEmissiveSampler = false;

        // Create emissive light sampler if it doesn't already exist.

        // Update the emissive sampler to the current frame.
        FALCOR_ASSERT(mpEmissiveSampler);

        mSpatialReusePass->getProgram()->addDefines(mpEmissiveSampler->getDefines());
        mTemporalReusePass->getProgram()->addDefines(mpEmissiveSampler->getDefines());
        mFinalShadingPass->getProgram()->addDefines(mpEmissiveSampler->getDefines());
        mpTraceRaysPass->getProgram()->addDefines(mpEmissiveSampler->getDefines());
        mGenerateFeaturePass->getProgram()->addDefines(mpEmissiveSampler->getDefines());

        mSpatialReusePass->setVars(nullptr);
        mTemporalReusePass->setVars(nullptr);
        mFinalShadingPass->setVars(nullptr);
        mpTraceRaysPass->setVars(nullptr);
        mGenerateFeaturePass->setVars(nullptr);

        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mSpatialReusePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mSpatialReusePass->getRootVar()["gScene"]);
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mTemporalReusePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mTemporalReusePass->getRootVar()["gScene"]);
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mFinalShadingPass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mFinalShadingPass->getRootVar()["gScene"]);
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mpTraceRaysPass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mpTraceRaysPass->getRootVar()["gScene"]);
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mGenerateFeaturePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mGenerateFeaturePass->getRootVar()["gScene"]);
    }

    if (mpScene->mNewEnvMapLoaded)
    {
        mpEnvMapSampler = std::make_unique<EnvMapSampler>(mpDevice, mpScene->getEnvMap());
        mSavedEnvMapRotation = mpScene->getEnvMap()->getRotation();
        mpScene->mNewEnvMapLoaded = false;
    }

    // Render resolution, which is NOT the swapchain size when a render scale is set.
    const uint2 renderDims = getRenderDims(renderData);
    mLastRenderDims = renderDims;
    uint32_t scrWidth = renderDims.x;
    uint32_t scrHeight = renderDims.y;

    // Install/refresh the camera jitter pattern for this render resolution. No-op (and resets jitter
    // to zero) for the default Center pattern.
    updateJitter(renderDims);

    // The camera aspect ratio is driven by the swapchain, not by this pass, so a render size with a
    // different aspect stretches the image. Half/Quarter are safe; Fixed is the user's to get right.
    {
        const uint2 dispDims = renderData.getDefaultTextureDims();
        mLastDisplayDims = dispDims;
        if (all(dispDims > 0u) && all(renderDims > 0u))
        {
            const float ar = float(renderDims.x) / float(renderDims.y);
            const float dispAr = float(dispDims.x) / float(dispDims.y);
            if (std::abs(ar - dispAr) > 0.005f * dispAr)
            {
                logWarning("VolumetricReSTIR: render size {}x{} has aspect {:.4f} but the display is "
                           "{}x{} (aspect {:.4f}); the image will be stretched.",
                           renderDims.x, renderDims.y, ar, dispDims.x, dispDims.y, dispAr);
            }
        }
    }

    bool wasOptionsChanged = mOptionsChanged;

    if (mOptionsChanged)
    {
        if (mRandomizeFrameSpeed) mFrameCount = rand() % 65536;
        else mFrameCount = 0;
        mTemporalSampleAccumulated = 0;
        Dictionary& dict = renderData.getDictionary();
        auto flags = dict.getValue(kRenderPassRefreshFlags, Falcor::RenderPassRefreshFlags::None);
        if (mOptionsChanged) flags |= Falcor::RenderPassRefreshFlags::RenderOptionsChanged;
        dict[Falcor::kRenderPassRefreshFlags] = flags;
        mOptionsChanged = false;
    }

    int reservoirCount = scrWidth * scrHeight;

    uint32_t reservoirSize = sizeof(Reservoir) + (mParams.mMaxBounces == 1 ? 0 : 4) + (mParams.mMaxBounces > 1 && mParams.mVertexReuse ? 4 : 0);

    if (mParams.mMaxBounces != mLastMaxBounces && !mParams.mUseReference)
    {
        mSpatialReusePass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
        mTemporalReusePass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
        mGenerateFeaturePass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
        mCopyReservoirPass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
        mFinalShadingPass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
        mpTraceRaysPass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
		mLastMaxBounces = mParams.mMaxBounces;
    }

    if (mParams.mMaxBounces > 1 && mLastVertexReuse != mParams.mVertexReuse)
    {
        if (mParams.mVertexReuse)
        {
            mSpatialReusePass->getProgram()->addDefine("VERTEX_REUSE");
            mTemporalReusePass->getProgram()->addDefine("VERTEX_REUSE");
            mGenerateFeaturePass->getProgram()->addDefine("VERTEX_REUSE");
            mFinalShadingPass->getProgram()->addDefine("VERTEX_REUSE");
            mCopyReservoirPass->getProgram()->addDefine("VERTEX_REUSE");
            mpTraceRaysPass->getProgram()->addDefine("VERTEX_REUSE");

            mSpatialReusePass->getProgram()->addDefine("REUSETYPE", "inout");
            mTemporalReusePass->getProgram()->addDefine("REUSETYPE", "inout");
            mGenerateFeaturePass->getProgram()->addDefine("REUSETYPE", "inout");
            mFinalShadingPass->getProgram()->addDefine("REUSETYPE", "inout");
            mpTraceRaysPass->getProgram()->addDefine("REUSETYPE", "inout");
        }
        else
        {
            mSpatialReusePass->getProgram()->removeDefine("VERTEX_REUSE");
            mTemporalReusePass->getProgram()->removeDefine("VERTEX_REUSE");
            mGenerateFeaturePass->getProgram()->removeDefine("VERTEX_REUSE");
            mCopyReservoirPass->getProgram()->removeDefine("VERTEX_REUSE");
            mFinalShadingPass->getProgram()->removeDefine("VERTEX_REUSE");
            mpTraceRaysPass->getProgram()->removeDefine("VERTEX_REUSE");

            mSpatialReusePass->getProgram()->addDefine("REUSETYPE", "");
            mTemporalReusePass->getProgram()->addDefine("REUSETYPE", "");
            mGenerateFeaturePass->getProgram()->addDefine("REUSETYPE", "");
            mFinalShadingPass->getProgram()->addDefine("REUSETYPE", "");
            mpTraceRaysPass->getProgram()->addDefine("REUSETYPE", "");
        }
        mLastVertexReuse = mParams.mVertexReuse;
    }

    // accumulated_color is an optional output: the graph compiler does not allocate an optional
    // output that is neither connected nor markOutput'd, so this must not be dereferenced blindly.
    ref<Texture> pColorOut = renderData.getTexture(kAccumulatedColorOutput);
    bool isScreenSizeChanged = pColorOut && (pColorOut->getHeight() != scrHeight || pColorOut->getWidth() != scrWidth);

    // compute extra bounce storage
    int totalReservoirCount = reservoirCount;
    int totalExtraBounceReservoirCount = reservoirCount * (mParams.mMaxBounces - 1);

    uint32_t ExtraBounceReservoirSizeCollection = (mParams.mMaxBounces - 1) * 12;

    if (!mParams.mUseReference && (isScreenSizeChanged || !mPerPixelReservoirBuffer[0] || wasOptionsChanged && mPerPixelReservoirBuffer[0]->getSize() != totalReservoirCount * reservoirSize))
    {
        printf("Total Reservoir Count: %d\n", totalReservoirCount);
        mPerPixelReservoirBuffer[0] = mpDevice->createStructuredBuffer(reservoirSize, totalReservoirCount);
        mPerPixelReservoirBuffer[1] = mpDevice->createStructuredBuffer(reservoirSize, totalReservoirCount);
        mTemporalReservoirBuffer = mpDevice->createStructuredBuffer(reservoirSize, totalReservoirCount);
        mReservoirFeatureBuffer = mpDevice->createStructuredBuffer(sizeof(ReservoirFeatures), totalReservoirCount);
        mTemporalReservoirFeatureBuffer = mpDevice->createStructuredBuffer(sizeof(ReservoirFeatures), totalReservoirCount);
        printf("Reservoir size: %d\n", (int)reservoirSize);
    }

    if (mParams.mUseSurfaceScene && (isScreenSizeChanged || !mVBuffer || wasOptionsChanged || (mPerPixelReservoirBuffer[0] && mPerPixelReservoirBuffer[0]->getSize() != totalReservoirCount * reservoirSize)))
    {
        mVBuffer = mpDevice->createStructuredBuffer(sizeof(VBufferItem), scrHeight * scrWidth);
        mTemporalVBuffer = mpDevice->createStructuredBuffer(sizeof(VBufferItem), scrHeight * scrWidth);
    }

    if (!mParams.mUseReference && mParams.mMaxBounces > 1 && (isScreenSizeChanged || !mPerPixelExtraBounceReservoirBuffer[0] || wasOptionsChanged && mPerPixelExtraBounceReservoirBuffer[0]->getSize() != totalExtraBounceReservoirCount * ExtraBounceReservoirSizeCollection))
    {
        mPerPixelExtraBounceReservoirBuffer[0] = mpDevice->createStructuredBuffer(ExtraBounceReservoirSizeCollection, totalExtraBounceReservoirCount);
        mPerPixelExtraBounceReservoirBuffer[1] = mpDevice->createStructuredBuffer(ExtraBounceReservoirSizeCollection, totalExtraBounceReservoirCount);
        mTemporalExtraBounceReservoirBuffer = mpDevice->createStructuredBuffer(ExtraBounceReservoirSizeCollection, totalExtraBounceReservoirCount);
    }


    // handle window resizing / change of temporal SPP
    if (!mPerPixelColorBuffer[0] ||
        isScreenSizeChanged)
    {
        mPerPixelColorBuffer[0] = mpDevice->createTexture2D(scrWidth, scrHeight, ResourceFormat::RGBA32Float, 1, 1, nullptr, ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
        mPerPixelColorBuffer[1] = mpDevice->createTexture2D(scrWidth, scrHeight, ResourceFormat::RGBA32Float, 1, 1, nullptr, ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    }

    int numInitialSamplingRounds = 1;
    int numTotalRounds = (int)(mParams.mEnableSpatialReuse ? mParams.mSpatialReuseRounds : 0) + (int)mParams.mEnableTemporalReuse + 1 + numInitialSamplingRounds;

    R2Params r2Params = { reservoirCount, mParams.mSpatialSampleCount, mParams.mSpatialReuseRounds, 16 };

    SamplingOptions initialOptions = {
    kAnalyticTracking,
    mParams.mInitialLightingTrackingMethod,
    mParams.mInitialLightSamples, // only 1 or 0
    mParams.mInitialLightingMipLevel,
    1,
    mParams.mInitialVisibilityUseLinearSampler ? mParams.mInitialBaseMipLevel : mParams.mInitialBaseMipLevel + kNumMaxMips,
    mParams.mInitialVisibilityUseLinearSampler,
    mParams.mInitialLightingUseLinearSampler,
    mParams.mInitialVisibilityTStepScale,
    mParams.mInitialLightingTStepScale,
    mParams.mUseEnvironmentLights, mParams.mUseAnalyticLights, mParams.mUseEmissiveLights, mParams.mVertexReuseStartBounce };

    SamplingOptions spatialOptions = {
    mParams.mSpatialVisibilityTrackingMethod,
    mParams.mSpatialLightingTrackingMethod,
    1,
    mParams.mSpatialLightingMipLevel,
    1,
    mParams.mSpatialVisibilityMipLevel,
    mParams.mSpatialVisibilityUseLinearSampler,
    mParams.mSpatialLightingUseLinearSampler,
    mParams.mSpatialVisibilityTStepScale,
    mParams.mSpatialLightingTStepScale,
    mParams.mUseEnvironmentLights, mParams.mUseAnalyticLights, mParams.mUseEmissiveLights, mParams.mVertexReuseStartBounce };

    // temporal use the same options as spatial

    SamplingOptions finalOptions = {
    mParams.mFinalVisibilityTrackingMethod,
    mParams.mFinalLightTrackingMethod,
    (mParams.mFinalLightTrackingMethod == kAnalyticTracking || mParams.mFinalLightTrackingMethod == kRayMarching) ? 1 : mParams.mFinalLightSamples,
    0, // mip level
    (mParams.mFinalVisibilityTrackingMethod == kAnalyticTracking || mParams.mFinalVisibilityTrackingMethod == kRayMarching) ? 1 : mParams.mFinalVisibilitySamples,
    0, // mip level
    true,
    true,
    mParams.mFinalTStepScale,
    mParams.mFinalTStepScale,
    mParams.mUseEnvironmentLights, mParams.mUseAnalyticLights, mParams.mUseEmissiveLights, mParams.mVertexReuseStartBounce };

    // Generate Feature Map. Also the producer of the DLSS guide buffers, so it must still run when
    // those are requested even if the frame is otherwise frozen (a stale depth/mvec would desync
    // the upscaler's history).
    if (!mFreezeFrame || mOutputDepth || mOutputVolumeGuides || mMotionVecMode == MotionVecMode::Deterministic)
    {
        FALCOR_PROFILE(pRenderContext, "Generate Features");

        auto vars = mGenerateFeaturePass->getRootVar();
        mpPixelDebug->prepareProgram(mGenerateFeaturePass->getProgram(), vars);

        mpScene->setVolumeShaderData(vars);
        vars["gLinearSampler"] = mpSampler;
        vars["gPointSampler"] = mpPointSampler;

        initialOptions.setShaderData(vars["CB"]["gInitialSamplingOptions"]);
        vars["CB"]["gResolution"] = uint2(scrWidth, scrHeight);
        vars["CB"]["gUseReference"] = mParams.mUseReference;
        vars["gReservoirFeatureBuffer"] = mReservoirFeatureBuffer;

        // Guide buffers. Both outputs are optional, so they are only allocated when something is
        // connected to them -- bind and enable only in that case.
        ref<Texture> pLinearZ = renderData.getTexture(kLinearZ);
        ref<Texture> pMotionVecDet = renderData.getTexture(kMotionVec);
        const bool writeDepth = mOutputDepth && pLinearZ != nullptr;
        const bool writeDetMV = (mMotionVecMode == MotionVecMode::Deterministic) && pMotionVecDet != nullptr;
        if (pLinearZ) vars["gLinearZ"] = pLinearZ;
        if (pMotionVecDet) vars["gMotionVec"] = pMotionVecDet;
        vars["CB"]["gOutputDepth"] = writeDepth;
        vars["CB"]["gOutputDeterministicMV"] = writeDetMV;
        vars["CB"]["gDepthAsNDC"] = mDepthAsNDC;

        // Each guide is gated on ITS OWN texture. These used to share one condition requiring both to
        // be allocated, so a graph that asked for only mediumAlpha got a silently zeroed buffer --
        // indistinguishable from the renderer computing zero. gOutputVolumeGuides now means only
        // "run the march", and is true if any of these is wanted.
        ref<Texture> pMediumAlpha = renderData.getTexture(kMediumAlpha);
        ref<Texture> pMediumNormal = renderData.getTexture(kMediumNormal);
        ref<Texture> pOpticalThickness = renderData.getTexture(kOpticalThickness);
        const bool writeAlpha = mOutputVolumeGuides && pMediumAlpha != nullptr;
        const bool writeNormal = mOutputVolumeGuides && pMediumNormal != nullptr;
        const bool writeTau = mOutputVolumeGuides && pOpticalThickness != nullptr;
        if (pMediumAlpha) vars["gMediumAlpha"] = pMediumAlpha;
        if (pMediumNormal) vars["gMediumNormal"] = pMediumNormal;
        if (pOpticalThickness) vars["gOpticalThickness"] = pOpticalThickness;
        // Scatter distance (NRD's hit-distance guide) rides the same march, so it has to be part of
        // the decision to run it -- a graph wanting only this and no other volume guide would
        // otherwise skip the block and get nothing.
        ref<Texture> pScatterDistance = renderData.getTexture(kScatterDistance);
        const bool writeScatter = mOutputVolumeGuides && pScatterDistance != nullptr;
        if (pScatterDistance) vars["gScatterDistance"] = pScatterDistance;

        ref<Texture> pVolumeVelocity = renderData.getTexture(kVolumeVelocity);
        ref<Texture> pScatterDensity = renderData.getTexture(kScatterDensity);
        const bool writeVelocity = mOutputVolumeGuides && pVolumeVelocity != nullptr;
        const bool writeDensity = mOutputVolumeGuides && pScatterDensity != nullptr;
        if (pVolumeVelocity) vars["gVolumeVelocity"] = pVolumeVelocity;
        if (pScatterDensity) vars["gScatterDensity"] = pScatterDensity;

        vars["CB"]["gOutputMediumAlpha"] = writeAlpha;
        vars["CB"]["gOutputMediumNormal"] = writeNormal;
        vars["CB"]["gOutputOpticalThickness"] = writeTau;
        vars["CB"]["gOutputScatterDistance"] = writeScatter;
        vars["CB"]["gOutputVolumeVelocity"] = writeVelocity;
        vars["CB"]["gOutputScatterDensity"] = writeDensity;
        vars["CB"]["gVolumeNormalMode"] = (uint32_t)mVolumeNormalMode;
        vars["CB"]["gOutputVolumeGuides"] =
            writeAlpha || writeNormal || writeTau || writeScatter || writeVelocity || writeDensity;

        if (mParams.mUseSurfaceScene)
        {
            vars["gVBuffer"] = mVBuffer;
        }
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mGenerateFeaturePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mGenerateFeaturePass->getRootVar()["gScene"]);
        mGenerateFeaturePass->execute(pRenderContext, uint3(renderDims, 1));
    }

    if (!mFreezeFrame)
    {
        FALCOR_PROFILE(pRenderContext, "Generate Samples");
        auto vars = mpTraceRaysPass->getRootVar();

        mpPixelDebug->prepareProgram(mpTraceRaysPass->getProgram(), vars);

        mpScene->setVolumeShaderData(vars);

        vars["gLinearSampler"] = mpSampler;
        vars["gPointSampler"] = mpPointSampler;

        vars["gOutputColor"] = mPerPixelColorBuffer[0];
        vars["gOutputReservoirs"] = mPerPixelReservoirBuffer[0];
        vars["gReservoirFeatureBuffer"] = mReservoirFeatureBuffer;
        vars["gOutputExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[0];
        if (mParams.mUseSurfaceScene)
            vars["gVBuffer"] = mVBuffer;

        vars["CB"]["gResolution"] = renderDims;
        vars["CB"]["gFrameCount"] = mFrameCount;
        vars["CB"]["gNumTotalRounds"] = numTotalRounds;
        vars["CB"]["gMaxBounces"] = mParams.mMaxBounces;
        vars["CB"]["gUseReference"] = mParams.mUseReference;
        vars["CB"]["gBaselineSamplePerPixel"] = mParams.mBaselineSamplePerPixel;
        vars["CB"]["gNumInitialSamples"] = mParams.mInitialM;
        vars["CB"]["gUseRussianRoulette"] = mParams.mInitialUseRussianRoulette;
        vars["CB"]["gNoReuse"] = !mParams.mEnableSpatialReuse && !mParams.mEnableTemporalReuse;
        vars["CB"]["gUseCoarserGridForIndirectBounce"] = mParams.mInitialUseCoarserGridForIndirectBounce;

        initialOptions.setShaderData(vars["CB"]["gInitialSamplingOptions"]);
        spatialOptions.setShaderData(vars["CB"]["gSpatialSamplingOptions"]);

        if (mpEnvMapSampler) mpEnvMapSampler->bindShaderData(vars["CB"]["envMapSampler"]);
        if (mpEmissiveSampler) mpEmissiveSampler->bindShaderData(vars["CB"]["emissiveSampler"]);

        if (mParams.mUseSurfaceScene)
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mpTraceRaysPass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mpTraceRaysPass->getRootVar()["gScene"]);

        mpTraceRaysPass->execute(pRenderContext, uint3(renderDims, 1));
    }

    int totalRoundId = 0;

    if (mFreezeFrame) totalRoundId = mParams.mEnableSpatialReuse ? 1 : 0;

    // temporal reuse
    if (!mFreezeFrame)
        if (!mParams.mUseReference && mParams.mEnableTemporalReuse)
        {
            FALCOR_PROFILE(pRenderContext, "Temporal Reuse");
            auto vars = mTemporalReusePass->getRootVar();

            mpPixelDebug->prepareProgram(mTemporalReusePass->getProgram(), vars);

            mpScene->setVolumeShaderData(vars);
            vars["gLinearSampler"] = mpSampler;
            vars["gPointSampler"] = mpPointSampler;

            spatialOptions.setShaderData(vars["CB"]["gSamplingOptions"]);

            vars["gCurReservoirs"] = mPerPixelReservoirBuffer[totalRoundId];
            vars["gTemporalReservoirs"] = mTemporalReservoirBuffer;
            vars["gCurExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[totalRoundId];
            vars["gTemporalExtraBounceReservoirs"] = mTemporalExtraBounceReservoirBuffer;
            vars["gReservoirFeatureBuffer"] = mReservoirFeatureBuffer;
            vars["gTemporalReservoirFeatureBuffer"] = mTemporalReservoirFeatureBuffer;
            // mvec is an optional output and is not allocated when it is neither connected nor
            // markOutput'd, so bind it only when it exists and suppress the shader write otherwise.
            ref<Texture> pMotionVec = renderData.getTexture(kMotionVec);
            if (pMotionVec) vars["gMotionVec"] = pMotionVec;

            if (mParams.mUseSurfaceScene)
            {
                vars["gVBuffer"] = mVBuffer;
                vars["gTemporalVBuffer"] = mTemporalVBuffer;
            }

            vars["CB"]["gResolution"] = uint2(scrWidth, scrHeight);
            vars["CB"]["gTemporalHistoryThreshold"] = mParams.mTemporalReuseMThreshold;
            vars["CB"]["gNumTotalRounds"] = numTotalRounds;
            vars["CB"]["gRoundOffset"] = numInitialSamplingRounds;
            vars["CB"]["gIsFirstFrame"] = mTemporalSampleAccumulated == 0;
            vars["CB"]["gFrameCount"] = mFrameCount;
            vars["CB"]["gPrevViewMat"] = mPrevViewMat;
            vars["CB"]["gPrevProjMat"] = mPrevProjMat;
            vars["CB"]["gPrevJitter"] = mApplyPrevJitter ? mPrevJitter : float2(0.f);
            vars["CB"]["gReprojectionMode"] = mParams.mTemporalReprojectionMode;
            vars["CB"]["gPrevCameraU"] = mPrevCameraU;
            vars["CB"]["gPrevCameraV"] = mPrevCameraV;
            vars["CB"]["gPrevCameraW"] = mPrevCameraW;
            vars["CB"]["gPrevCameraPosW"] = mPrevCameraPosW;
            vars["CB"]["gMISMethod"] = mParams.mTemporalMISMethod;
            // Only the legacy writer runs here; the deterministic one lives in GenerateFeatures.
            // Never let both target the same texture.
            vars["CB"]["gOutputMotionVec"] = (mMotionVecMode == MotionVecMode::Legacy) && pMotionVec != nullptr;
            vars["CB"]["gReprojectionMipLevel"] = mParams.mTemporalReprojectionMipLevel;

            if (mpEnvMapSampler) mpEnvMapSampler->bindShaderData(vars["CB"]["envMapSampler"]);
            if (mpEmissiveSampler) mpEmissiveSampler->bindShaderData(vars["CB"]["emissiveSampler"]);

            if (mParams.mUseSurfaceScene)
            if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mTemporalReusePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mTemporalReusePass->getRootVar()["gScene"]);

            mTemporalReusePass->execute(pRenderContext, (int)scrWidth , (int)scrHeight );

            if (!mParams.mEnableSpatialReuse)
            {
                pRenderContext->copyResource(mTemporalReservoirBuffer.get(), mPerPixelReservoirBuffer[totalRoundId].get());
                if (mTemporalExtraBounceReservoirBuffer && mParams.mMaxBounces > 1)
                    pRenderContext->copyResource(mTemporalExtraBounceReservoirBuffer.get(), mPerPixelExtraBounceReservoirBuffer[totalRoundId].get());
            }

            pRenderContext->copyResource(mTemporalReservoirFeatureBuffer.get(), mReservoirFeatureBuffer.get());
            if (mParams.mUseSurfaceScene)
                pRenderContext->copyResource(mTemporalVBuffer.get(), mVBuffer.get());
        }

    if (!mFreezeFrame)
        if (!mParams.mUseReference && mParams.mEnableSpatialReuse)
            // spatial reuse
        {
            FALCOR_PROFILE(pRenderContext, "Spatial Reuse");

            int startRoundId = 0;
            int endRoundId = mParams.mSpatialReuseRounds;

            int totalRoundIdBackup = totalRoundId;
            totalRoundId = totalRoundIdBackup;
            for (int roundId = startRoundId; roundId < endRoundId; roundId++)
            {
                auto vars = mSpatialReusePass->getRootVar();
                mpPixelDebug->prepareProgram(mSpatialReusePass->getProgram(), vars);

                mpScene->setVolumeShaderData(vars);
                vars["gLinearSampler"] = mpSampler;
                vars["gPointSampler"] = mpPointSampler;

                vars["gInputReservoirs"] = mPerPixelReservoirBuffer[totalRoundId % 2];
                vars["gOutputReservoirs"] = mPerPixelReservoirBuffer[(totalRoundId + 1) % 2];
                vars["gInputColors"] = mPerPixelColorBuffer[totalRoundId % 2];
                vars["gOutputColors"] = mPerPixelColorBuffer[(totalRoundId + 1) % 2];
                vars["gInputExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[totalRoundId % 2];
                vars["gOutputExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[(totalRoundId + 1) % 2];
                vars["gReservoirFeatureBuffer"] = mReservoirFeatureBuffer;
                if (mParams.mUseSurfaceScene)
                    vars["gVBuffer"] = mVBuffer;

                spatialOptions.setShaderData(vars["CB"]["gSamplingOptions"]);
                r2Params.setShaderData(vars["CB"]["gR2Params"]);

                vars["CB"]["gResolution"] = uint2(scrWidth, scrHeight);
                vars["CB"]["gFrameCount"] = mFrameCount;
                vars["CB"]["gRoundId"] = roundId;
                vars["CB"]["gNumRounds"] = mParams.mSpatialReuseRounds;
                vars["CB"]["gRoundOffset"] = (int)mParams.mEnableTemporalReuse + numInitialSamplingRounds;
                vars["CB"]["gMISMethod"] = mParams.mSpatialMISMethod;
                vars["CB"]["gRandomSamplerType"] = mParams.mRandomSamplerType;
                vars["CB"]["gSampleRadius"] = mParams.mSampleRadius;
                vars["CB"]["gSampleCount"] = mParams.mSpatialSampleCount;

                if (mpEnvMapSampler) mpEnvMapSampler->bindShaderData(vars["CB"]["envMapSampler"]);
                if (mpEmissiveSampler) mpEmissiveSampler->bindShaderData(vars["CB"]["emissiveSampler"]);

                if (mParams.mUseSurfaceScene)
                if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mSpatialReusePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mSpatialReusePass->getRootVar()["gScene"]);

                mSpatialReusePass->execute(pRenderContext, (int)scrWidth , (int)scrHeight );
                totalRoundId++;
            }
        }

    if (!mFreezeFrame)
        if (!mParams.mUseReference && mParams.mEnableTemporalReuse)
        {
            // launch a shader to copy resources
            FALCOR_PROFILE(pRenderContext, "Copy resource");

            auto vars = mCopyReservoirPass->getRootVar();
            vars["CB"]["gResolution"] = uint2(scrWidth, scrHeight);

            if (mParams.mMaxBounces > 1)
            {
                vars["gCurExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[totalRoundId % 2];
                vars["gTemporalExtraBounceReservoirs"] = mTemporalExtraBounceReservoirBuffer;
            }
            vars["gCurReservoirs"] = mPerPixelReservoirBuffer[totalRoundId % 2];
            vars["gTemporalReservoirs"] = mTemporalReservoirBuffer;
            mCopyReservoirPass->execute(pRenderContext, uint3(renderDims, 1));
        }

    {
        FALCOR_PROFILE(pRenderContext, "Final Shading");

        auto vars = mFinalShadingPass->getRootVar();

        mpPixelDebug->prepareProgram(mFinalShadingPass->getProgram(), vars);

        mpScene->setVolumeShaderData(vars);
        vars["gLinearSampler"] = mpSampler;
        vars["gPointSampler"] = mpPointSampler;

        vars["gCurrentColors"] = mPerPixelColorBuffer[totalRoundId % 2];
        vars["gCurReservoirs"] = mPerPixelReservoirBuffer[totalRoundId % 2];
        vars["gCurExtraBounceReservoirs"] = mPerPixelExtraBounceReservoirBuffer[totalRoundId % 2];
        vars["gOutputFrame"] = renderData[kAccumulatedColorOutput]->asTexture();
        vars["gReservoirFeatureBuffer"] = mReservoirFeatureBuffer;

        // Optional, so only bound (and only enabled) when the graph asked for it.
        ref<Texture> pLightDir = renderData.getTexture(kLightDir);
        if (pLightDir)
            vars["gLightDir"] = pLightDir;
        vars["CB"]["gOutputLightDir"] = pLightDir != nullptr;

        if (mParams.mUseSurfaceScene)
            vars["gVBuffer"] = mVBuffer;

        finalOptions.setShaderData(vars["CB"]["gSamplingOptions"]);

        vars["CB"]["gResolution"] = uint2(scrWidth, scrHeight);
        vars["CB"]["gNumTotalRounds"] = numTotalRounds;
        vars["CB"]["gFrameCount"] = mFreezeFrame ? mFrameCount - 1 : mFrameCount;
        vars["CB"]["gSpatialReuse"] = mParams.mEnableSpatialReuse;
        vars["CB"]["gTemporalReuse"] = mParams.mEnableTemporalReuse;
        vars["CB"]["gUseReference"] = mParams.mUseReference;
        vars["CB"]["gMaxBounces"] = mParams.mMaxBounces;
        vars["CB"]["gVisualizeTotalTransmittance"] = mParams.mVisualizeTotalTransmittance;
        vars["CB"]["gNoReuse"] = !mParams.mEnableSpatialReuse && !mParams.mEnableTemporalReuse;

        if (mpEnvMapSampler) mpEnvMapSampler->bindShaderData(vars["CB"]["envMapSampler"]);
        if (mpEmissiveSampler) mpEmissiveSampler->bindShaderData(vars["CB"]["emissiveSampler"]);

        if (mParams.mUseSurfaceScene)
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mFinalShadingPass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mFinalShadingPass->getRootVar()["gScene"]);

        mFinalShadingPass->execute(pRenderContext, scrWidth, scrHeight);
    }


    mTemporalSampleAccumulated = 1;

    // See mTransposePrevMatrices in the header: TemporalReuse consumes these with the 4.x
    // `mul(v, M)`, so under Falcor 8's row-major layout they must be transposed here.
    mPrevViewMat = mpScene->getCamera()->getViewMatrix();
    mPrevProjMat = mpScene->getCamera()->getProjMatrix();
    if (mTransposePrevMatrices)
    {
        mPrevViewMat = transpose(mPrevViewMat);
        mPrevProjMat = transpose(mPrevProjMat);
    }
    {
        const CameraData& cd = mpScene->getCamera()->getData();
        mPrevCameraU = cd.cameraU;
        mPrevCameraV = cd.cameraV;
        mPrevCameraW = cd.cameraW;
        mPrevCameraPosW = cd.posW;
        // Snapshot the jitter too: the previous frame's reservoirs were generated on a ray built
        // with THIS jitter, so reconstructing that ray without it makes p-hat wrong for that domain.
        mPrevJitter = float2(cd.jitterX, cd.jitterY);
    }

    if (!mFreezeFrame)
        mFrameCount++;

    if (!mFreezeFrame && !mFreezeAnimation)
        mAnimationFrameCount++;

    if (mAnimationFrameCount == mAnimationFreezedFrame)
    {
        mFreezeFrame = true;
    }

    mpPixelDebug->endFrame(pRenderContext);

    // Update point lights

    float animationTime = (float)mAnimationFrameCount;

    if (mAnimateEnvLight)
    {
        float rotationSpeed = mEnvLightRotationSpeed;
        float rotDeg = 60 * sin(animationTime * rotationSpeed);
        mpScene->getEnvMap()->setRotation(float3(0, rotDeg, 0));
    }
    else // reset envlight rotation
    {
        if (mLastAnimateEnvLight != mAnimateEnvLight)
            mpScene->getEnvMap()->setRotation(mSavedEnvMapRotation);
    }
    mLastAnimateEnvLight = mAnimateEnvLight;

    if (mCameraFramesMoved > 0)
    {
        if (mCameraAnimationMode == 0)
        {
            int roundFrames = mCameraShakeRoundsBeforePause * mCameraFrameInterval + mCameraPauseInterval;
            int totalFrames = mCameraShakeTotalRounds * (mCameraShakeRoundsBeforePause * mCameraFrameInterval + mCameraPauseInterval);
            float cameraMoveSpeed = 2 * (float)M_PI / mCameraFrameInterval;

            if (mCameraFramesMoved++ < totalFrames)
            {
                int roundSubFrameId = mCameraFramesMoved % roundFrames;
                if (roundSubFrameId < mCameraShakeRoundsBeforePause * mCameraFrameInterval)
                {
                    mFreezeFrame = false;
                    mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
                    moveCameraRight(sin(cameraMoveSpeed * mCameraFramesMoved) * mCameraMoveScale, mBackedupCameraPosition);
                }
                else
                {
                    mFreezeFrame = true;
                    mpScene->mPauseVDBAnimation = true;
                }
            }
        }
        else if (mCameraAnimationMode == 1)
        {
            if (mCameraFramesMoved++ < 6 * mCameraFrameInterval)
            {
                int frameInterval = mCameraFrameInterval;

                float cameraMoveSpeed = 2 * (float)M_PI / frameInterval;

                if (mCameraFramesMoved < frameInterval)
                {
                    moveCameraRight(sin(cameraMoveSpeed * mCameraFramesMoved) * mCameraMoveScale, mBackedupCameraPosition);
                }
                else if (mCameraFramesMoved >= frameInterval && mCameraFramesMoved < 2 * frameInterval)
                {
                    mFreezeFrame = true;
                    mpScene->mPauseVDBAnimation = true;
                }
                else if (mCameraFramesMoved >= 2 * frameInterval && mCameraFramesMoved < 3 * frameInterval)
                {
                    mFreezeFrame = false;
                    mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
                    moveCameraRight(sin(cameraMoveSpeed * (mCameraFramesMoved - frameInterval)) * mCameraMoveScale, mBackedupCameraPosition);
                    mBackedupCameraPosition2 = mpScene->getCamera()->getPosition();
                }
                else if (mCameraFramesMoved >= 3 * frameInterval && mCameraFramesMoved < 3 * frameInterval + frameInterval / 4)
                {
                    mFreezeFrame = false;
                    mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
                    _forwardCameraInterval(mCameraForwardScale * cos(cameraMoveSpeed * (mCameraFramesMoved - 3 * frameInterval)), mBackedupCameraPosition2);
                }
                else if (mCameraFramesMoved >= 3 * frameInterval + frameInterval / 4 && mCameraFramesMoved < 4 * frameInterval + frameInterval / 4)
                {
                    mFreezeFrame = true;
                    mpScene->mPauseVDBAnimation = true;
                }
                else if (mCameraFramesMoved >= 4 * frameInterval + frameInterval / 4 && mCameraFramesMoved < 4 * frameInterval + 3 * frameInterval / 4)
                {
                    mFreezeFrame = false;
                    mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
                    _forwardCameraInterval(mCameraForwardScale * cos(cameraMoveSpeed * (mCameraFramesMoved - 4 * frameInterval)), mBackedupCameraPosition2);
                }
                else if (mCameraFramesMoved >= 4 * frameInterval + 3 * frameInterval / 4 && mCameraFramesMoved < 5 * frameInterval + 3 * frameInterval / 4)
                {
                    mFreezeFrame = true;
                    mpScene->mPauseVDBAnimation = true;
                }
                else if (mCameraFramesMoved >= 5 * frameInterval + 3 * frameInterval / 4 && mCameraFramesMoved < 6 * frameInterval)
                {
                    mFreezeFrame = false;
                    mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;
                    _forwardCameraInterval(mCameraForwardScale * cos(cameraMoveSpeed * (mCameraFramesMoved - 5 * frameInterval)), mBackedupCameraPosition2);
                }
            }
        }
        else
        {
            float cameraMoveSpeed = 2 * (float)M_PI / mCameraFrameInterval;

            // find a point that is on the initial view ray and closest to the volume center to be the center
            float3 rotCenter = mBackedupCameraPosition + dot(mpScene->getSceneVolumeCenter() - mBackedupCameraPosition, normalize(mBackedupCameraTarget - mBackedupCameraPosition)) * normalize(mBackedupCameraTarget - mBackedupCameraPosition);

            if (mCameraFramesMoved++ < mCameraRotationFrames)
            {
                mFreezeFrame = false;
                mpScene->mPauseVDBAnimation = mSavedVDBAnimationState;

                float angleRotated = mCameraFramesMoved * mCameraRotationSpeed * (float)M_PI / 180.f;

                float3 Xdir = normalize(mBackedupCameraPosition - rotCenter);
                float3 Ydir = normalize(cross(float3(0,1,0), Xdir));
                Xdir = normalize(cross(Ydir, float3(0, 1, 0)));

                float3 actualRotCenter = rotCenter + (mBackedupCameraPosition - rotCenter) - (dot((mBackedupCameraPosition - rotCenter), Xdir) * Xdir);

                float camDist = mCameraRotationDistance <= 0 ? length(mBackedupCameraPosition - actualRotCenter) : mCameraRotationDistance;
                float3 camPos = actualRotCenter + camDist * (Xdir * cos(angleRotated) + Ydir * sin(angleRotated));
                mpScene->getCamera()->setPosition(camPos);
                mpScene->getCamera()->setTarget(rotCenter);
            }
        }
    }
}

void VolumetricReSTIR::renderUI(Gui::Widgets& widget)
{
    bool dirty = false;

    // Render scale. Changing this reallocates the pass outputs, so it needs a graph recompile --
    // hence requestRecompile() rather than just setting the value. Any downstream upscaler (DLSS
    // SR or Ray Reconstruction) picks up the new input size on its next execute and reinitialises
    // itself, so the whole chain follows from this one control.
    if (auto scaleGroup = widget.group("Render scale", true))
    {
        // The switch. Everything else in this group is subordinate to it.
        // Graph-wide, not per-pass: Ray Reconstruction needs colour, depth, motion vectors and guides
        // at one resolution, so every producing pass has to move together.
        if (scaleGroup.checkbox("Upscaling", mUpscaling))
        {
            setRenderScale(mUpscaling, mUpscaleRatio);
            requestRecompile();
        }
        scaleGroup.tooltip(
            "Render below display resolution and let the downstream DLSS pass (SR or Ray "
            "Reconstruction) reconstruct full resolution. This is what frees compute budget: ReSTIR "
            "traces fewer pixels, and the saving goes back into sampling. Off = native resolution.",
            true
        );

        if (mUpscaling)
        {
            // A ratio of the display, not a size: cannot be given a wrong aspect, and follows the
            // swapchain across a window resize without being touched again.
            if (scaleGroup.slider("Render ratio", mUpscaleRatio, 0.25f, 1.0f))
            {
                setRenderScale(mUpscaling, mUpscaleRatio);
                requestRecompile();
            }
            scaleGroup.tooltip("Linear ratio. Pixel count is its square -- 0.58 renders 34% of the pixels.", true);

            // The DLSS profiles, so the ratio can be matched to the downstream pass in one click.
            auto preset = [&](const char* label, float r, const char* tip)
            {
                if (scaleGroup.button(label, true))
                {
                    mUpscaleRatio = r;
                    setRenderScale(mUpscaling, mUpscaleRatio);
                    requestRecompile();
                }
                scaleGroup.tooltip(tip, true);
            };
            preset("MaxPerf", 0.5f, "50% -- matches DLSS MaxPerf (25% of the pixels)");
            preset("Balanced", 0.58f, "58% -- matches DLSS Balanced (34% of the pixels)");
            preset("Quality", 0.667f, "67% -- matches DLSS MaxQuality (44% of the pixels)");

            const uint2 disp = all(mLastDisplayDims > 0u) ? mLastDisplayDims : uint2(1920, 1080);
            const uint2 pred = upscaledRenderSize(disp);
            scaleGroup.text(fmt::format("{}x{} -> {}x{}   ({:.0f}% of the pixels)", pred.x, pred.y, disp.x, disp.y,
                                        100.f * float(pred.x * pred.y) / float(std::max(1u, disp.x * disp.y))));
        }
        else
        {
            // Manual override, kept for the non-DLSS experiments (Half/Quarter, or an exact size).
            if (scaleGroup.dropdown("Output size", mOutputSizeSelection))
                requestRecompile();

            if (mOutputSizeSelection == RenderPassHelpers::IOSize::Fixed)
            {
                uint2 fixedSize = mFixedOutputSize;
                if (scaleGroup.var("Fixed size", fixedSize, 32u, 8192u))
                {
                    mFixedOutputSize = fixedSize;
                    requestRecompile();
                }
                scaleGroup.tooltip(
                    "Render resolution. Keep the display's aspect ratio -- the camera aspect comes "
                    "from the swapchain, so a mismatch stretches the image (the pass warns when it "
                    "differs by more than 0.5%). The Upscaling switch above avoids this entirely.",
                    true
                );
            }
        }

        scaleGroup.text(fmt::format("Rendering at {}x{}  (display {}x{})", mLastRenderDims.x, mLastRenderDims.y, mLastDisplayDims.x, mLastDisplayDims.y));
    }

    if (auto logGroup = widget.group("Logging"))
    {
        // Pixel debugger.
        mpPixelDebug->renderUI(logGroup);
    }


    if (mpScene && mParams.mUseEmissiveLights)
    {
        widget.text("Emissive sampler:");
        widget.tooltip("Selects which light sampler to use for importance sampling of emissive geometry.", true);
        if (widget.dropdown("##EmissiveSampler", kEmissiveSamplerList, (uint32_t&)mEmissiveSamplerType, true))
        {
            mpEmissiveSampler = nullptr;
            dirty = true;
        }
    }

    if (mpEmissiveSampler)
    {
        if (auto emissiveGroup = widget.group("Emissive sampler options"))
        {
            if (mpEmissiveSampler->renderUI(emissiveGroup))
            {
                // Get the latest options for the current sampler. We need these to re-create the sampler at scene changes and for pass serialization.
                switch (mEmissiveSamplerType)
                {
                case EmissiveLightSamplerType::LightBVH:
                    mLightBVHSamplerOptions = dynamic_cast<LightBVHSampler*>(mpEmissiveSampler.get())->getOptions();
                    break;
                default:
                    break;
                }
                dirty = true;
            }
        }
    }


    auto group_ = Gui::Group(widget, "Animation", false);
    if (group_.open())
    {
        bool isDirty = widget.checkbox("Animate Env Lights", mAnimateEnvLight);
        if (isDirty && mAnimateEnvLight) {
            mAnimationFrameCount = 0;
            mpScene->getEnvMap()->setRotation(mSavedEnvMapRotation);
            mAnimationStartTime = 0;
        }
        isDirty |= widget.var("Env Light Animation Speed", mEnvLightRotationSpeed);
        dirty |= isDirty;

        widget.var("camera frame interval", mCameraFrameInterval, 10, 2000);
        widget.var("camera move scale", mCameraMoveScale, 0.01f, 20.f);

        Gui::DropdownList op;
        op.push_back({ 0, "Shake" });
        op.push_back({ 1, "Shake+Zoom" });
        op.push_back({ 2, "Rotation" });
        widget.dropdown("camera animation mode (press \"B\" to animate)", op, mCameraAnimationMode);

        if (mCameraAnimationMode == 0)
        {
            widget.var("camera pause interval", mCameraPauseInterval, 10, 2000);
            widget.var("camera shake total rounds", mCameraShakeTotalRounds, 1, 5);
            widget.var("camera shake rounds before pause", mCameraShakeRoundsBeforePause, 1, 20);
        }
        else if (mCameraAnimationMode == 1)
        {
            widget.var("camera forward scale", mCameraForwardScale, 0.01f, 100.f);
        }
        else
        {
            widget.var("camera rotation frames", mCameraRotationFrames, 1, 129600);
            widget.var("camera rotation speed", mCameraRotationSpeed, 0.001f, 10.f);
            widget.var("camera rotation distance", mCameraRotationDistance, 0.f, 100.f);
        }

        dirty |= widget.var("Freeze At Animation Frame", mAnimationFreezedFrame, -1, 5000);

        dirty |= isDirty;
        group_.release();
    }

    dirty |= mpScene->renderVolumeUI(widget);

    auto group = Gui::Group(widget, "VolumetricReSTIR", true);

    if (group.open())
    {
        auto groupReservoir = Gui::Group(widget, "ReSTIR settings", true);

        if (groupReservoir.open())
        {
            dirty |= widget.checkbox("Temporal Reuse", mParams.mEnableTemporalReuse);
            dirty |= widget.checkbox("Spatial Reuse", mParams.mEnableSpatialReuse);
            dirty |= widget.checkbox("Vertex Reuse", mParams.mVertexReuse);
            dirty |= widget.var("Vertex Reuse Start Bounce", mParams.mVertexReuseStartBounce, 1, 64);
            dirty |= widget.checkbox("Visualize Total Transmittance", mParams.mVisualizeTotalTransmittance);

            groupReservoir.release();
        }

        auto groupGen = Gui::Group(widget, "General Settings", true);

        if (groupGen.open())
        {
            bool isFreezeChanged = widget.checkbox("Freeze Frame", mFreezeFrame);
            if (isFreezeChanged)
            {
                mpScene->mFreezeCamera = mFreezeFrame;
                if (mFreezeFrame)
                    mSavedVDBAnimationState = mpScene->mPauseVDBAnimation;
                mpScene->mPauseVDBAnimation = mFreezeFrame ? true : mSavedVDBAnimationState;
            }

            // global controls
            dirty |= widget.var("max bounces", mParams.mMaxBounces, 1, 64);

            dirty |= widget.checkbox("Use Volume Path Tracing", mParams.mUseReference);
            widget.tooltip("Switch to baseline (volume path tracing).");
            if (mParams.mUseReference)
            {
                dirty |= widget.var("Volume Path Tracing spp", mParams.mBaselineSamplePerPixel, 1, 32);
            }

            dirty |= widget.checkbox("use environment lights", mParams.mUseEnvironmentLights);
            dirty |= widget.checkbox("use analytic lights", mParams.mUseAnalyticLights);
            dirty |= widget.checkbox("use emissive lights", mParams.mUseEmissiveLights);

            groupGen.release();
        }


        auto group0 = Gui::Group(widget, "Initial Sampling", false);
        if (group0.open())
        {
            dirty |= widget.var("M", mParams.mInitialM, 1, 32);

            dirty |= widget.var("Initial Tracking Mip Level", mParams.mInitialBaseMipLevel, 0, mpScene->getVolumeNumMips() - 1);
            widget.tooltip("Volume mip-map level used for regular tracking to produce the initial samples.");
            dirty |= widget.var("NEE Transmittance Mip Level", mParams.mInitialLightingMipLevel, 0, mpScene->getVolumeNumMips() - 1);
            widget.tooltip("Volume mip-map level used for estimate the light transmittance of the initial samples.");

            dirty |= widget.checkbox("Use Trilinear Reg Tracking", mParams.mInitialVisibilityUseLinearSampler);
            widget.tooltip("Regular tracking with trilinear density (more expensive).");
            dirty |= widget.checkbox("NEE Transmittance Use Linear Sampler", mParams.mInitialLightingUseLinearSampler);
            widget.tooltip("Use trilinearly filtered density for estimating transmittance.");

            //dirty |= widget.var("Vis T Step Scale (for total transmittance)", mParams.mInitialVisibilityTStepScale, 1.f, 10.f);
            dirty |= widget.checkbox("Use Coarser Grid for Reg Tracking Indirect Bounces", mParams.mInitialUseCoarserGridForIndirectBounce);
            widget.tooltip("Use Initial Tracking Mip Level + 1 for bounce > 0");
            dirty |= widget.var("NEE Transmittance T Step Scale", mParams.mInitialLightingTStepScale, 1.f, 10.f);
            widget.tooltip("Step size (X times voxel size) in ray marching.");

            dirty |= widget.checkbox("Use Russian Roulette", mParams.mInitialUseRussianRoulette);


            bool computeTL = mParams.mInitialLightSamples == 0 ? false : true;
            bool changed = widget.checkbox("Compute NEE Transmittance", computeTL);
            widget.tooltip("Use volumetric shadow in target PDF for initial resampling");
            if (changed) mParams.mInitialLightSamples = computeTL ? 1 : 0;
            dirty |= changed;

            {
                Gui::DropdownList op;

                uint32_t temp = mParams.mInitialLightingTrackingMethod - kAnalyticTracking;
                op.push_back({ 0, "Regular" });
                op.push_back({ 1, "Ray Marching" });
                dirty |= widget.dropdown("Light Tracking Method", op, temp);
				mParams.mInitialLightingTrackingMethod = temp + kAnalyticTracking;
            }
            group0.release();
        }

        auto group__ = Gui::Group(widget, "Spatiotemporal Shared Options", false);

        if (group__.open())
        {
            {
                dirty |= widget.var("Transmittance Mip Level", mParams.mSpatialVisibilityMipLevel, 0, mpScene->getVolumeNumMips() - 1);
                widget.tooltip("Shared volume mip-map level used for primary visibility resampling for spatial/temporal neighbors.");
                dirty |= widget.var("NEE Transmittance Mip Level", mParams.mSpatialLightingMipLevel, 0, mpScene->getVolumeNumMips() - 1);
                widget.tooltip("Shared volume mip-map level used for light transmittance resampling for spatial/temporal neighbors.");
            }

            {
                dirty |= widget.checkbox("Transmittance Use Linear Sampler", mParams.mSpatialVisibilityUseLinearSampler);
                dirty |= widget.checkbox("NEE Transmittance Use Linear Sampler", mParams.mSpatialLightingUseLinearSampler);
            }

            {
                dirty |= widget.var("Transmittance T Step Scale", mParams.mSpatialVisibilityTStepScale, 1.f, 10.f);
                dirty |= widget.var("NEE Transmittance T Step Scale", mParams.mSpatialLightingTStepScale, 1.f, 10.f);
                widget.tooltip("Step size (X times voxel size) in ray marching.");
            }


            {
                Gui::DropdownList op;
                op.push_back({ 0, "Regular" });
                op.push_back({ 1, "Ray Marching" });

                uint32_t tempVis = mParams.mSpatialVisibilityTrackingMethod - kAnalyticTracking;
                uint32_t tempLight = mParams.mSpatialLightingTrackingMethod - kAnalyticTracking;

                dirty |= widget.dropdown("Transmittance Tracking Method", op, tempVis);
                dirty |= widget.dropdown("NEE Transmittance Tracking Method", op, tempLight);

                mParams.mSpatialVisibilityTrackingMethod = tempVis + kAnalyticTracking;
                mParams.mSpatialLightingTrackingMethod = tempLight + kAnalyticTracking;
            }

            group__.release();
        }

        auto group2 = Gui::Group(widget, "Spatial Reuse Options", false);
        if (group2.open())
        {
            dirty |= widget.var("Spatial Reuse Rounds", mParams.mSpatialReuseRounds, 0, 9);

            {
                Gui::DropdownList op;
                op.push_back({ 0, "Hammersley" });
                op.push_back({ 1, "R2" });
                dirty |= widget.dropdown("Sampler Type", op, mParams.mRandomSamplerType);
                widget.tooltip("Using R2 allows rotating the spatial kernel per frame.");
            }

            dirty |= widget.var("Sample Radius", mParams.mSampleRadius, 1.f, 100.f);
            dirty |= widget.var("Sample Count", mParams.mSpatialSampleCount, 1, 16);
            widget.tooltip("Total spatial sample count, which is number of spatial neighbors + 1.");


            {
                Gui::DropdownList op;
                op.push_back({ 0, "No MIS (biased)" });
                op.push_back({ 1, "Talbot MIS" });
                dirty |= widget.dropdown("MIS Method", op, mParams.mSpatialMISMethod);
            }

            group2.release();
        }

        auto group3 = Gui::Group(widget, "Temporal Reuse Options", false);
        if (group3.open())
        {
            dirty |= widget.var("Temporal Reuse M threshold", mParams.mTemporalReuseMThreshold, 0.f, 1000.f);
            widget.tooltip("A value X Limits the temporal reservoir's M to X times current frame's reservoir's M.");

            {
                Gui::DropdownList op;
                op.push_back({ 0, "Reproject with Velocity Resampling" });
                op.push_back({ 1, "No Reprojection" });
                op.push_back({ 2, "Reproject without Velocity Resampling" });
                dirty |= widget.dropdown("Reprojection Mode", op, mParams.mTemporalReprojectionMode);
            }

            dirty |= widget.var("Reprojection Mip Level", mParams.mTemporalReprojectionMipLevel, 0, mpScene->getVolumeNumMips() - 1);
            {
                Gui::DropdownList op;
                op.push_back({ 0, "No MIS (biased when moving)" });
                op.push_back({ 1, "Talbot MIS" });

                dirty |= widget.dropdown("MIS Method", op, mParams.mTemporalMISMethod);
            }

            group3.release();
        }

        auto group5 = Gui::Group(widget, "Final Shading Options", false);
        widget.tooltip("Sampling options to estimate the final integrand F.");
        if (group5.open())
        {
            {
                Gui::DropdownList op;
                op.push_back({ 0, "Ratio" });
                op.push_back({ 1, "Analytic" });
                op.push_back({ 2, "Ray Marching (biased)" });
                op.push_back({ 3, "Residual Ratio Tracking" });
                op.push_back({ 4, "Analog Residual Ratio Tracking" });

                dirty |= widget.dropdown("Transmittance Tracking method", op, mParams.mFinalVisibilityTrackingMethod);
                if (!(mParams.mFinalVisibilityTrackingMethod == kAnalyticTracking || mParams.mFinalVisibilityTrackingMethod == kRayMarching))
                    dirty |= widget.var("Transmittance samples", mParams.mFinalVisibilitySamples, 1, 16);

                dirty |= widget.dropdown("NEE transmittance tracking method", op, mParams.mFinalLightTrackingMethod);
                if (!(mParams.mFinalLightTrackingMethod == kAnalyticTracking || mParams.mFinalLightTrackingMethod == kRayMarching))
                    dirty |= widget.var("NEE transmittance samples", mParams.mFinalLightSamples, 1, 16);
            }

            group5.release();
        }

        group.release();
    }

    if (dirty) mOptionsChanged = true;
}

void VolumetricReSTIR::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    if (pScene)
    {
        mpScene = pScene;

        // [8.0 surface-scene] The surface path uses the scene's material system, so its programs must
        // link the scene's shader modules + material type conformances. Recreate them here (the scene
        // isn't available at construction time). Volume-only scenes keep the plain passes.
        if (mParams.mUseSurfaceScene)
        {
            mpTraceRaysPass = createSceneComputePass(mpDevice, kShaderDirectory + "TraceRays.cs.slang", "main", mDefaultDefines, pScene);
            mSpatialReusePass = createSceneComputePass(mpDevice, kShaderDirectory + "SpatialReuse.cs.slang", "main", mDefaultDefines, pScene);
            mTemporalReusePass = createSceneComputePass(mpDevice, kShaderDirectory + "TemporalReuse.cs.slang", "main", mDefaultDefines, pScene);
            mGenerateFeaturePass = createSceneComputePass(mpDevice, kShaderDirectory + "GenerateFeatures.cs.slang", "main", mDefaultDefines, pScene);
            mCopyReservoirPass = createSceneComputePass(mpDevice, kShaderDirectory + "CopyReservoirs.cs.slang", "main", mDefaultDefines, pScene);
            mFinalShadingPass = createSceneComputePass(mpDevice, kShaderDirectory + "FinalShading.cs.slang", "main", mDefaultDefines, pScene);
        }

        this->updateSceneDefines(mpTraceRaysPass, pScene);
        this->updateSceneDefines(mSpatialReusePass, pScene);
        this->updateSceneDefines(mTemporalReusePass, pScene);
        this->updateSceneDefines(mGenerateFeaturePass, pScene);
        this->updateSceneDefines(mFinalShadingPass, pScene);
        // [8.0 port] CopyReservoirs also needs its vars created (compute passes are created with
        // createVars=false); without this its getRootVar() null-derefs during temporal reuse.
        this->updateSceneDefines(mCopyReservoirPass, pScene);

        mpScene->getCurrentVolumeDesc().usePrevGridForReproj = mParams.mUsePrevVolumeForReproj;

        mpTraceRaysPass->getProgram()->addDefines(mpSampleGenerator->getDefines());
        mSpatialReusePass->getProgram()->addDefines(mpSampleGenerator->getDefines());
        mTemporalReusePass->getProgram()->addDefines(mpSampleGenerator->getDefines());
        mGenerateFeaturePass->getProgram()->addDefines(mpSampleGenerator->getDefines());
        mFinalShadingPass->getProgram()->addDefines(mpSampleGenerator->getDefines());

        mpSampleGenerator->bindShaderData(mpTraceRaysPass->getRootVar());
        mpSampleGenerator->bindShaderData(mSpatialReusePass->getRootVar());
        mpSampleGenerator->bindShaderData(mTemporalReusePass->getRootVar());
        mpSampleGenerator->bindShaderData(mGenerateFeaturePass->getRootVar());
        mpSampleGenerator->bindShaderData(mFinalShadingPass->getRootVar());

        if (pScene->getEnvMap())
        {
            mSavedEnvMapRotation = mpScene->getEnvMap()->getRotation();
            mpEnvMapSampler = std::make_unique<EnvMapSampler>(mpDevice, pScene->getEnvMap());
        }

        mpEmissiveSampler = nullptr;

        overrideVolumeDesc();
    }

    mInitialCameraPosition = mpScene->getCamera()->getPosition();
    mInitialCameraTarget = mpScene->getCamera()->getTarget();
}

bool VolumetricReSTIR::onMouseEvent(const MouseEvent& mouseEvent)
{
    return mpPixelDebug->onMouseEvent(mouseEvent);
}

bool VolumetricReSTIR::onKeyEvent(const KeyboardEvent& keyEvent)
{
    if (keyEvent.type == KeyboardEvent::Type::KeyPressed && keyEvent.key == Input::Key::R)
    {
        resetCamera(false);
        mOptionsChanged = true;
        return true;
    }

    if (keyEvent.type == KeyboardEvent::Type::KeyPressed && keyEvent.key == Input::Key::B)
    {
        toggleCameraAnimation();
    }

    return false;
}

void VolumetricReSTIR::setProperties(const Properties& props)
{
    parseProperties(props);

    if ((int)mEmissiveSamplerType != mEmissiveSamplerTypeId)
    {
        if (mEmissiveSamplerTypeId == 0)
            mEmissiveSamplerType = EmissiveLightSamplerType::Uniform;
        else if (mEmissiveSamplerTypeId == 1)
            mEmissiveSamplerType = EmissiveLightSamplerType::LightBVH;
        else if (mEmissiveSamplerTypeId == 2)
            mEmissiveSamplerType = EmissiveLightSamplerType::Power;

        mpEmissiveSampler = nullptr;
    }

    // reset animation
    if (mVolumeAnimationSelectedFrameId == -1)
    {
        if (mpScene->mUseAnimatedVolume)
            mpScene->mVDBAnimationFrameId = -1;
        else
            mpScene->mVDBAnimationFrameId = 0;
        mpScene->mPauseVDBAnimation = false;
    }
    else
    {
        mpScene->mVDBAnimationFrameId = mVolumeAnimationSelectedFrameId - 1;
        mpScene->mPauseVDBAnimation = true;
    }

    overrideVolumeDesc();
    mpScene->getCurrentVolumeDesc().usePrevGridForReproj = mParams.mUsePrevVolumeForReproj;

    mAnimationFrameCount = 0;
    mpScene->getEnvMap()->setRotation(mSavedEnvMapRotation);

    if (props.has("ToggleCameraAnimation"))
    {
        toggleCameraAnimation();
    }

    if (props.has("moveCameraRight"))
    {
        float distance = props.get<float>("moveCameraRight");
        moveCameraRight(distance, mInitialCameraPosition);
    }

    if (props.has("resetCamera"))
    {
        resetCamera(false);
    }

    if (props.has("randomizeFrameSeed"))
    {
        if (!mRandomizeFrameSpeed) srand(123);
        mRandomizeFrameSpeed = true;
    }

    mOptionsChanged = true;

    if (props.has("moveCameraRight"))
    {
        mOptionsChanged = false;
    }

    printf("update pass!\n");
}
