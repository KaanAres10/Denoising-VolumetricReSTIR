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

    const Falcor::ChannelList kOutputChannels =
    {
        // [8.0 port] accumulated_color is written as a UAV by FinalShading, so it needs an explicit
        // UAV-capable format (RGBA32Float). Without a format it defaults to the swapchain's
        // BGRA8UnormSrgb, which does not support UnorderedAccess.
        { kAccumulatedColorOutput,     "gOutputFrame",    "accumulated output color (linear)", true /* optional */, ResourceFormat::RGBA32Float      },
        { kMotionVec,     "gMotionVec",    "motion vector", true /* optional */, ResourceFormat::RG32Float      }
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
    return props;
}

RenderPassReflection VolumetricReSTIR::reflect(const CompileData& compileData)
{
    // Define the required resources here
    RenderPassReflection reflector;
    addRenderPassOutputs(reflector, kOutputChannels);
    return reflector;
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

    mpPixelDebug->beginFrame(pRenderContext, renderData.getDefaultTextureDims());

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

    uint32_t scrWidth = renderData.getDefaultTextureDims().x;
    uint32_t scrHeight = renderData.getDefaultTextureDims().y;

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

    bool isScreenSizeChanged = renderData[kAccumulatedColorOutput]->asTexture()->getHeight() != scrHeight || renderData[kAccumulatedColorOutput]->asTexture()->getWidth() != scrWidth;

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

    // Generate Feature Map
    if (!mFreezeFrame)
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
        if (mParams.mUseSurfaceScene)
        {
            vars["gVBuffer"] = mVBuffer;
        }
        if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(pRenderContext, mGenerateFeaturePass->getRootVar()["gScene"], 0); else mpScene->bindShaderData(mGenerateFeaturePass->getRootVar()["gScene"]);
        mGenerateFeaturePass->execute(pRenderContext, uint3(renderData.getDefaultTextureDims(), 1));
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

        vars["CB"]["gResolution"] = renderData.getDefaultTextureDims();
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

        mpTraceRaysPass->execute(pRenderContext, uint3(renderData.getDefaultTextureDims(), 1));
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
            vars["gMotionVec"] = renderData[kMotionVec]->asTexture();

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
            vars["CB"]["gReprojectionMode"] = mParams.mTemporalReprojectionMode;
            vars["CB"]["gPrevCameraU"] = mPrevCameraU;
            vars["CB"]["gPrevCameraV"] = mPrevCameraV;
            vars["CB"]["gPrevCameraW"] = mPrevCameraW;
            vars["CB"]["gPrevCameraPosW"] = mPrevCameraPosW;
            vars["CB"]["gMISMethod"] = mParams.mTemporalMISMethod;
            vars["CB"]["gOutputMotionVec"] = mOutputMotionVec;
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
            mCopyReservoirPass->execute(pRenderContext, uint3(renderData.getDefaultTextureDims(), 1));
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

    mPrevViewMat = mpScene->getCamera()->getViewMatrix();
    mPrevProjMat = mpScene->getCamera()->getProjMatrix();
    {
        const CameraData& cd = mpScene->getCamera()->getData();
        mPrevCameraU = cd.cameraU;
        mPrevCameraV = cd.cameraV;
        mPrevCameraW = cd.cameraW;
        mPrevCameraPosW = cd.posW;
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
