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
#include "Core/Enum.h"
#include "Core/API/Shared/D3D12DescriptorSet.h"
#include "Core/API/Shared/D3D12RootSignature.h"
#include "Core/API/Shared/D3D12ConstantBufferView.h"
#include "RenderGraph/RenderPassHelpers.h"

#include <NRD.h>

using namespace Falcor;

class NRDPass : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(NRDPass, "NRD", "NRD denoiser.");

    /// Existing values keep their ordinals: these are serialized into render-graph scripts, so
    /// renumbering silently reinterprets saved graphs as a different denoiser. New v4 entries are
    /// appended only.
    enum class DenoisingMethod : uint32_t
    {
        RelaxDiffuseSpecular,
        RelaxDiffuse,
        ReblurDiffuseSpecular,
        SpecularReflectionMv, // v3.1 only -- removed in v4
        SpecularDeltaMv,      // v3.1 only -- removed in v4
        // --- v4 only, appended ---
        RelaxSpecular,
        ReblurDiffuse,
        ReblurSpecular,
        ReblurDiffuseOcclusion,
        SigmaShadow,
        SigmaShadowTranslucency,
        Reference,
        RelaxDiffuseSh,
        ReblurDiffuseSh,
    };

    FALCOR_ENUM_INFO(
        DenoisingMethod,
        {
            {DenoisingMethod::RelaxDiffuseSpecular, "RelaxDiffuseSpecular"},
            {DenoisingMethod::RelaxDiffuse, "RelaxDiffuse"},
            {DenoisingMethod::ReblurDiffuseSpecular, "ReblurDiffuseSpecular"},
            {DenoisingMethod::SpecularReflectionMv, "SpecularReflectionMv"},
            {DenoisingMethod::SpecularDeltaMv, "SpecularDeltaMv"},
            {DenoisingMethod::RelaxSpecular, "RelaxSpecular"},
            {DenoisingMethod::ReblurDiffuse, "ReblurDiffuse"},
            {DenoisingMethod::ReblurSpecular, "ReblurSpecular"},
            {DenoisingMethod::ReblurDiffuseOcclusion, "ReblurDiffuseOcclusion"},
            {DenoisingMethod::SigmaShadow, "SigmaShadow"},
            {DenoisingMethod::SigmaShadowTranslucency, "SigmaShadowTranslucency"},
            {DenoisingMethod::Reference, "Reference"},
            {DenoisingMethod::RelaxDiffuseSh, "RelaxDiffuseSh"},
            {DenoisingMethod::ReblurDiffuseSh, "ReblurDiffuseSh"},
        }
    );

    static ref<NRDPass> create(ref<Device> pDevice, const Properties& props) { return make_ref<NRDPass>(pDevice, props); }

    NRDPass(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pRenderContext, const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;
    virtual void setScene(RenderContext* pRenderContext, const ref<Scene>& pScene) override;

private:
    ref<Scene> mpScene;
    uint2 mScreenSize{};
    uint32_t mFrameIndex = 0;
    RenderPassHelpers::IOSize mOutputSizeSelection = RenderPassHelpers::IOSize::Default;

    void reinit();
    void createPipelines();
    void createResources();
    void executeInternal(RenderContext* pRenderContext, const RenderData& renderData);
    void dispatch(RenderContext* pRenderContext, const RenderData& renderData, const nrd::DispatchDesc& dispatchDesc);

#if FALCOR_HAS_NRD4
    /// v4 renames the opaque handle: an "Instance" hosts one or more denoisers, each keyed by an
    /// application-chosen Identifier. (v4 reuses the name "Denoiser" for what v3.1 called "Method".)
    nrd::Instance* mpInstance = nullptr;
    /// The identifier we register our single denoiser under. Any uint32_t will do as long as it is
    /// unique within the instance; CreateInstance returns NON_UNIQUE_IDENTIFIER otherwise.
    static constexpr nrd::Identifier kDenoiserIdentifier = 0;
#else
    nrd::Denoiser* mpDenoiser = nullptr;
#endif

    bool mEnabled = true;
    DenoisingMethod mDenoisingMethod = DenoisingMethod::RelaxDiffuseSpecular;
    bool mRecreateDenoiser = false;
    bool mWorldSpaceMotion = true;
    float mMaxIntensity = 1000.f;
    float mDisocclusionThreshold = 2.f;
#if FALCOR_HAS_NRD4
    /// v4 CommonSettings additions. Defaults mirror the SDK's own so behaviour is unchanged until
    /// something is deliberately altered.
    float mDisocclusionThresholdAlternate = 5.f;   ///< Percent, as with mDisocclusionThreshold.
    float mStrandThickness = 80e-6f;
    float mStrandMaterialID = 999.f;
    float mCameraAttachedReflectionMaterialID = 999.f;
    float mSplitScreen = 0.f;                      ///< [0;1] noisy input vs denoised, for eyeballing.
    /// Renders NRD's own debug view (viewZ, normals, motion, history length) into OUT_VALIDATION.
    /// The output is only reflected when this is on, so turning it on triggers a graph recompile.
    bool mEnableValidation = false;
#endif
    nrd::CommonSettings mCommonSettings = {};
#if FALCOR_HAS_NRD4
    /// v4 merges RelaxDiffuseSettings + RelaxDiffuseSpecularSettings + RelaxSpecularSettings into
    /// one struct shared by all six RELAX denoisers.
    nrd::RelaxSettings mRelaxSettings = {};
#else
    nrd::RelaxDiffuseSpecularSettings mRelaxDiffuseSpecularSettings = {};
    nrd::RelaxDiffuseSettings mRelaxDiffuseSettings = {};
#endif
    nrd::ReblurSettings mReblurSettings = {};
#if FALCOR_HAS_NRD4
    /// SIGMA (shadow) and REFERENCE (accumulate-only) take their own settings structs. Kept at SDK
    /// defaults; SigmaSettings::lightDirection matters only for directional lights.
    nrd::SigmaSettings mSigmaSettings = {};
    nrd::ReferenceSettings mReferenceSettings = {};
#endif

    std::vector<ref<Sampler>> mpSamplers;
    std::vector<D3D12DescriptorSetLayout> mCBVSRVUAVdescriptorSetLayouts;
    ref<D3D12DescriptorSet> mpSamplersDescriptorSet;
    std::vector<ref<D3D12RootSignature>> mpRootSignatures;
    std::vector<ref<ComputePass>> mpPasses;
    std::vector<ref<const ProgramKernels>> mpCachedProgramKernels;
    std::vector<ref<ComputeStateObject>> mpCSOs;
    std::vector<ref<Texture>> mpPermanentTextures;
    std::vector<ref<Texture>> mpTransientTextures;
    ref<D3D12ConstantBufferView> mpCBV;

    float4x4 mPrevViewMatrix;
    float4x4 mPrevProjMatrix;

#if FALCOR_HAS_NRD4
    /// v4 requires the PREVIOUS frame's resolution and jitter in CommonSettings; v3.1 had no such
    /// concept. All default to zero, and zeros degrade reprojection silently rather than erroring,
    /// so these must be carried frame to frame.
    uint2 mPrevResourceSize = {};
    uint2 mPrevRectSize = {};
    float2 mPrevCameraJitter = {};
    /// Pool textures are sized from CommonSettings::resourceSize in v4 (TextureDesc no longer
    /// carries width/height), so a resolution change must reallocate them.
    uint2 mPoolResourceSize = {};
#endif

    // Additional classic Falcor compute pass and resources for packing radiance and hitT for NRD.
    ref<ComputePass> mpPackRadiancePassRelax;
    ref<ComputePass> mpPackRadiancePassReblur;
};

FALCOR_ENUM_REGISTER(NRDPass::DenoisingMethod);
