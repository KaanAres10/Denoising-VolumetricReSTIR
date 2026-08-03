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
#include "Falcor.h"
#include "Core/API/NativeHandleTraits.h"

#include "NRDPass.h"
#include "RenderPasses/Shared/Denoising/NRDConstants.slang"

namespace
{
const char kShaderPackRadiance[] = "RenderPasses/NRDPass/PackRadiance.cs.slang";
#if FALCOR_HAS_NRD4
const char kShaderResolveSh[] = "RenderPasses/NRDPass/ResolveSh.cs.slang";
const char kShResolveMode[] = "shResolveMode";
const char kEnableValidation[] = "enableValidation";
#endif

// Input buffer names.
const char kInputDiffuseRadianceHitDist[] = "diffuseRadianceHitDist";
const char kInputSpecularRadianceHitDist[] = "specularRadianceHitDist";
const char kInputSpecularHitDist[] = "specularHitDist";
const char kInputMotionVectors[] = "mvec";
const char kInputNormalRoughnessMaterialID[] = "normWRoughnessMaterialID";
const char kInputViewZ[] = "viewZ";
const char kInputDeltaPrimaryPosW[] = "deltaPrimaryPosW";
const char kInputDeltaSecondaryPosW[] = "deltaSecondaryPosW";
#if FALCOR_HAS_NRD4
// v4 optional inputs. All are declared optional in reflect(): NRD is told they exist only when the
// graph actually connects them (isHistoryConfidenceAvailable / isDisocclusionThresholdMixAvailable),
// because claiming an input that is not bound reads as "confidence 0 everywhere" rather than failing.
const char kInputDiffuseConfidence[] = "diffuseConfidence";
const char kInputSpecularConfidence[] = "specularConfidence";
const char kInputDisocclusionThresholdMix[] = "disocclusionThresholdMix";
// Occlusion / SIGMA / REFERENCE denoiser IO.
const char kInputDiffuseHitDist[] = "diffuseHitDist";
const char kInputPenumbra[] = "penumbra";
const char kInputTranslucency[] = "translucency";
const char kInputSignal[] = "signal";
#endif

// Output buffer names.
const char kOutputFilteredDiffuseRadianceHitDist[] = "filteredDiffuseRadianceHitDist";
const char kOutputFilteredSpecularRadianceHitDist[] = "filteredSpecularRadianceHitDist";
const char kOutputReflectionMotionVectors[] = "reflectionMvec";
const char kOutputDeltaMotionVectors[] = "deltaMvec";
#if FALCOR_HAS_NRD4
const char kOutputValidation[] = "validation";
const char kOutputFilteredDiffuseHitDist[] = "filteredDiffuseHitDist";
const char kOutputShadowTranslucency[] = "shadowTranslucency";
const char kOutputSignal[] = "filteredSignal";
// SH mode emits a PAIR per signal; SH0 carries {c0, chroma.xy, normHitDist} and SH1 {c1.xyz, sharpness}.
const char kOutputDiffuseSh0[] = "filteredDiffuseSh0";
const char kOutputDiffuseSh1[] = "filteredDiffuseSh1";
const char kInputDiffuseSh0[] = "diffuseSh0";
const char kInputDiffuseSh1[] = "diffuseSh1";
#endif

// Serialized parameters.

const char kEnabled[] = "enabled";
const char kMethod[] = "method";
const char kOutputSize[] = "outputSize";

// Common settings.
const char kWorldSpaceMotion[] = "worldSpaceMotion";
const char kDisocclusionThreshold[] = "disocclusionThreshold";

// Pack radiance settings.
const char kMaxIntensity[] = "maxIntensity";

// ReLAX diffuse/specular settings.
const char kDiffusePrepassBlurRadius[] = "diffusePrepassBlurRadius";
const char kSpecularPrepassBlurRadius[] = "specularPrepassBlurRadius";
const char kDiffuseMaxAccumulatedFrameNum[] = "diffuseMaxAccumulatedFrameNum";
const char kSpecularMaxAccumulatedFrameNum[] = "specularMaxAccumulatedFrameNum";
const char kDiffuseMaxFastAccumulatedFrameNum[] = "diffuseMaxFastAccumulatedFrameNum";
const char kSpecularMaxFastAccumulatedFrameNum[] = "specularMaxFastAccumulatedFrameNum";
const char kDiffusePhiLuminance[] = "diffusePhiLuminance";
const char kSpecularPhiLuminance[] = "specularPhiLuminance";
const char kDiffuseLobeAngleFraction[] = "diffuseLobeAngleFraction";
const char kSpecularLobeAngleFraction[] = "specularLobeAngleFraction";
const char kRoughnessFraction[] = "roughnessFraction";
const char kDiffuseHistoryRejectionNormalThreshold[] = "diffuseHistoryRejectionNormalThreshold";
const char kSpecularVarianceBoost[] = "specularVarianceBoost";
const char kSpecularLobeAngleSlack[] = "specularLobeAngleSlack";
const char kDisocclusionFixEdgeStoppingNormalPower[] = "disocclusionFixEdgeStoppingNormalPower";
const char kDisocclusionFixMaxRadius[] = "disocclusionFixMaxRadius";
const char kDisocclusionFixNumFramesToFix[] = "disocclusionFixNumFramesToFix";
const char kHistoryClampingColorBoxSigmaScale[] = "historyClampingColorBoxSigmaScale";
const char kSpatialVarianceEstimationHistoryThreshold[] = "spatialVarianceEstimationHistoryThreshold";
const char kAtrousIterationNum[] = "atrousIterationNum";
const char kMinLuminanceWeight[] = "minLuminanceWeight";
const char kDepthThreshold[] = "depthThreshold";
const char kRoughnessEdgeStoppingRelaxation[] = "roughnessEdgeStoppingRelaxation";
const char kNormalEdgeStoppingRelaxation[] = "normalEdgeStoppingRelaxation";
const char kLuminanceEdgeStoppingRelaxation[] = "luminanceEdgeStoppingRelaxation";
const char kEnableAntiFirefly[] = "enableAntiFirefly";
const char kEnableReprojectionTestSkippingWithoutMotion[] = "enableReprojectionTestSkippingWithoutMotion";
const char kEnableSpecularVirtualHistoryClamping[] = "enableSpecularVirtualHistoryClamping";
const char kEnableRoughnessEdgeStopping[] = "enableRoughnessEdgeStopping";
const char kEnableMaterialTestForDiffuse[] = "enableMaterialTestForDiffuse";
const char kEnableMaterialTestForSpecular[] = "enableMaterialTestForSpecular";

#if FALCOR_HAS_NRD4
/// The guide layout, as ONE value rather than a number repeated per call site.
///
/// Three things have to agree on this and none of them validates the others: the macros NRD's shaders
/// are compiled with (`NRD_NORMAL_ENCODING` / `NRD_ROUGHNESS_ENCODING`), what `NRDAdapter.cs.slang`
/// packs, and what the linked NRD binary was built to expect. When they disagree the guides decode to
/// noise, every edge-stopping weight fails, and the output is a uniformly smeared frame -- there is no
/// error. That happened once already, because v4 renamed these macros and silently ignored the v3.1
/// names. `reinit()` now cross-checks these against `GetLibraryDesc()`, which closes the third leg.
///
/// Values are shared between `NRD.hlsli`'s `NRD_NORMAL_ENCODING_*` macros and `nrd::NormalEncoding` /
/// `nrd::RoughnessEncoding` -- the enums are declared in the same order as the macros, which is what
/// makes comparing them meaningful.
constexpr uint32_t kNrdNormalEncoding = 2;    // R10_G10_B10_A2_UNORM: normal+roughness co-packed, materialID in A2
constexpr uint32_t kNrdRoughnessEncoding = 1; // LINEAR
#endif

#if FALCOR_HAS_NRD4
/// Shared by the RELAX and REBLUR panels -- both settings structs carry the same enum.
///
/// OFF is correct for this renderer and is the SDK default: reconstruction exists for PROBABILISTIC
/// sampling at the primary hit, where a pixel may carry no hit distance at all. VolumetricReSTIR does
/// not do that, and NRD's own note warns the modes additionally assume the sampling probability was
/// clamped and Bayer dithering used. Exposed for completeness and for surface graphs (PathTracerNRD).
const Gui::DropdownList kHitDistanceReconstructionMode = {
    {(uint32_t)nrd::HitDistanceReconstructionMode::OFF, "Off"},
    {(uint32_t)nrd::HitDistanceReconstructionMode::AREA_3X3, "3x3"},
    {(uint32_t)nrd::HitDistanceReconstructionMode::AREA_5X5, "5x5"},
};

void renderHitDistReconstructionUI(Gui::Group& group, nrd::HitDistanceReconstructionMode& mode)
{
    group.dropdown("Hit distance reconstruction", kHitDistanceReconstructionMode, reinterpret_cast<uint32_t&>(mode));
    group.tooltip(
        "For probabilistic sampling at the primary hit only. This renderer does not sample "
        "probabilistically, so Off is correct here."
    );
}
#endif // FALCOR_HAS_NRD4

// Expose only togglable methods.
// There is no reason to expose runtime toggle for other methods.
const Gui::DropdownList kDenoisingMethod = {
    {(uint32_t)NRDPass::DenoisingMethod::RelaxDiffuseSpecular, "ReLAX"},
    {(uint32_t)NRDPass::DenoisingMethod::ReblurDiffuseSpecular, "ReBLUR"},
};
} // namespace

NRDPass::NRDPass(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    mpDevice->requireD3D12();

    // PackRadiance includes NRD.hlsli, so it needs the SAME encoding macros as the library shaders.
    // v4 renamed them; see the note in createPipelines(). Passing the v3.1 names to a v4 build is a
    // silent no-op, which is exactly how a guide-layout mismatch goes unnoticed.
    DefineList definesEncoding;
#if FALCOR_HAS_NRD4
    definesEncoding.add("NRD_V4");
    definesEncoding.add("NRD_NORMAL_ENCODING", "2");
    definesEncoding.add("NRD_ROUGHNESS_ENCODING", "1");
#else
    definesEncoding.add("NRD_USE_OCT_NORMAL_ENCODING", "1");
    definesEncoding.add("NRD_USE_MATERIAL_ID", "0");
#endif

    DefineList definesRelax = definesEncoding;
    definesRelax.add("NRD_METHOD", "0"); // NRD_METHOD_RELAX_DIFFUSE_SPECULAR
    mpPackRadiancePassRelax = ComputePass::create(mpDevice, kShaderPackRadiance, "main", definesRelax);

    DefineList definesReblur = definesEncoding;
    definesReblur.add("NRD_METHOD", "1"); // NRD_METHOD_REBLUR_DIFFUSE_SPECULAR
    mpPackRadiancePassReblur = ComputePass::create(mpDevice, kShaderPackRadiance, "main", definesReblur);

#if FALCOR_HAS_NRD4
    // Both resolve variants are compiled up front so an SH shader error surfaces here, beside the
    // rest of the setup, rather than on whichever frame the mode is first switched.
    DefineList definesResolve = definesEncoding;
    definesResolve.add("NRD_INTERNAL");
    definesResolve.add("SH_RESOLVE_MODE", "0"); // SH_RESOLVE_DC
    mpResolveShPassDc = ComputePass::create(mpDevice, kShaderResolveSh, "main", definesResolve);
    definesResolve.add("SH_RESOLVE_MODE", "1"); // SH_RESOLVE_COSINE
    mpResolveShPassCosine = ComputePass::create(mpDevice, kShaderResolveSh, "main", definesResolve);
#endif

#if FALCOR_HAS_NRD4
    // Deliberately NOT porting the v3.1 overrides below. Many were tuned against v3.1 semantics that
    // no longer hold: diffuse/specularLobeAngleFraction merged into one lobeAngleFraction,
    // disocclusionFixMaxRadius (a float radius) became historyFixBasePixelStride (a uint32 stride),
    // enableSpecularVirtualHistoryClamping was removed, and several v4 defaults moved on purpose
    // (roughnessFraction 0.05 -> 0.15, depthThreshold 0.01 -> 0.003). Carrying the old numbers over
    // would silently reproduce v3.1-era tuning against a different filter. Start from NRD's own v4
    // defaults; retune later against measurements if wanted.
    //
    // Only the few overrides that still mean exactly what they used to are kept.
    mRelaxSettings.diffuseMaxFastAccumulatedFrameNum = 2;
    mRelaxSettings.specularMaxFastAccumulatedFrameNum = 2;
    mRelaxSettings.atrousIterationNum = 6;
    mRelaxSettings.spatialVarianceEstimationHistoryThreshold = 4;

    // The pre-pass MUST be off for volumetric input. v4 sizes its kernel as
    //     blurRadius = prepassBlurRadius * saturate(hitDist / frustumSize)     [RELAX_PrePass.cs.hlsl]
    // which assumes "hitDist" is a short secondary-bounce length, so the factor is normally well
    // below 1. We feed the expected SCATTER distance through a participating medium, which is the
    // same order as the frustum itself -- the factor saturates to 1 and the pre-pass degenerates
    // into a full-radius blur over the entire frame, guides notwithstanding.
    //
    // Measured on plume against the converged reference (MSE), everything else at v4 defaults:
    //     radius 30 (v4 default) 2.009e-02   <- worse than the raw, undenoised input
    //     radius 16 (v3.1 value) 1.091e-02
    //     radius  8              5.307e-03
    //     radius  4              2.325e-03
    //     radius  1              1.209e-03
    //     radius  0              1.072e-03
    // Monotonic, so this is not a tuning optimum -- the pre-pass has no useful regime here.
    // NVIDIA's own guidance agrees it is optional: "must be used in case of probabilistic sampling",
    // which this renderer does not do.
    //
    // NOTE: this is also the ONLY route by which hit distance reaches RELAX in v4 (confirmed by
    // ablation: with the pre-pass off, VR_NRD_HITDIST=0 is byte-identical). v3.1 ignored hit
    // distance in RELAX entirely, so scatterDistance now only earns its keep under REBLUR.
    mRelaxSettings.diffusePrepassBlurRadius = 0.f;
    mRelaxSettings.specularPrepassBlurRadius = 0.f;

    // New in v4 for RELAX (v3.1 exposed antifirefly on REBLUR only). Our input is 1-spp volumetric
    // radiance, which is exactly the firefly-heavy case it exists for. Small but consistent win:
    // 1.072e-03 -> 1.059e-03 on plume.
    mRelaxSettings.enableAntiFirefly = true;

    // History reconstruction off, for the same reason as the pre-pass. It exists to invent a signal
    // for pixels that have NO temporal history yet (post-disocclusion), by blurring across a 5x5
    // kernel with a 14-pixel stride -- a ~28 pixel footprint. That trade is right when the
    // alternative is a 1-spp surface estimate with nothing behind it. It is wrong here: when NRD
    // resets a pixel's history, the underlying VolumetricReSTIR estimate is still a converged
    // multi-frame average, so the blur replaces good data with a wide average of its neighbours.
    //
    // Measured (MSE vs converged reference), historyFixFrameNum 3 (v4 default) -> 0:
    //     bistro  2.132e-04 -> 7.707e-05   (2.8x better)
    //     plume   1.059e-03 -> 1.059e-03   (byte-identical; no history resets to fix)
    // Strictly non-negative: it either helps or costs nothing on the scenes we have.
    //
    // THAT CONCLUSION WAS WRONG, and specifically wrong because of how it was measured. Every number
    // above was taken with a PINNED camera. History fix exists for pixels that have just been
    // DISOCCLUDED, and a static camera barely disoccludes anything -- so the test could not see what
    // the setting is for, and "strictly non-negative" only held inside that regime.
    //
    // Measured again with the camera moving on a fixed dolly (scratchpad flicker harness: capture
    // consecutive frames, take the SECOND temporal difference so smooth motion cancels and only
    // flicker remains), bistro, single denoiser:
    //
    //     historyFixFrameNum 0 (ours)                 0.46561
    //     historyFixFrameNum 3 (NRD default)          0.41773   -10.3%
    //     + diffusePrepassBlurRadius 30 (NRD default) 0.41464   -10.9%
    //
    // So NRD's default is restored. The static-scene MSE win for 0 is real but regime-specific, and
    // a still camera is not the case this renderer is for.
    //
    // NOTE the opposite holds for the SPLIT path (VR_NRD_SPLIT=1): there each half of the radiance is
    // punched through with structural zeros where the other half won the reservoir, and both of these
    // settings work by spreading information spatially, so they spread the zeros and make it worse.
    // That is why the split tunes its two branches separately.
    mRelaxSettings.historyFixFrameNum = 3;

    // Debug overrides for the settings above. Not a substitute for Properties -- these exist so the
    // measurements quoted in this file (and in README.md) can be reproduced without a rebuild, and
    // so a regression can be bisected against NRD's own defaults. Unset = use the value above.
    auto envF = [](const char* n, float d)
    { const char* v = std::getenv(n); return v ? std::strtof(v, nullptr) : d; };
    auto envU = [](const char* n, uint32_t d)
    { const char* v = std::getenv(n); return v ? uint32_t(std::strtoul(v, nullptr, 10)) : d; };
    mRelaxSettings.diffusePrepassBlurRadius = envF("NRD4_PREPASS", mRelaxSettings.diffusePrepassBlurRadius);
    mRelaxSettings.enableAntiFirefly = envU("NRD4_ANTIFIREFLY", mRelaxSettings.enableAntiFirefly ? 1u : 0u) != 0u;
    mRelaxSettings.atrousIterationNum = envU("NRD4_ATROUS", mRelaxSettings.atrousIterationNum);
    mRelaxSettings.diffuseMaxAccumulatedFrameNum = envU("NRD4_MAXACCUM", mRelaxSettings.diffuseMaxAccumulatedFrameNum);
    mRelaxSettings.diffuseMaxFastAccumulatedFrameNum =
        envU("NRD4_FASTACCUM", mRelaxSettings.diffuseMaxFastAccumulatedFrameNum);
    mRelaxSettings.historyFixFrameNum = envU("NRD4_HISTFIX", mRelaxSettings.historyFixFrameNum);
    mRelaxSettings.diffusePhiLuminance = envF("NRD4_PHILUM", mRelaxSettings.diffusePhiLuminance);
    mRelaxSettings.fastHistoryClampingSigmaScale =
        envF("NRD4_CLAMPSIGMA", mRelaxSettings.fastHistoryClampingSigmaScale);
    mRelaxSettings.spatialVarianceEstimationHistoryThreshold =
        envU("NRD4_SVAR", mRelaxSettings.spatialVarianceEstimationHistoryThreshold);
    mDisocclusionThreshold = envF("NRD4_DISOCC", mDisocclusionThreshold);

    // Two RELAX knobs left at NRD's defaults until now, exposed because they target the SPLIT path's
    // specific weakness. Splitting the radiance leaves each half punched through with structural
    // zeros wherever the other half won the reservoir; RELAX's luminance edge-stopping sees a zero
    // pixel beside a bright one, reads a huge luminance difference, and refuses to blend them -- so
    // the holes survive filtering. A floor on that weight forces it to blend across them.
    mRelaxSettings.diffuseMinLuminanceWeight = envF("NRD4_MINLUMW", mRelaxSettings.diffuseMinLuminanceWeight);
    mRelaxSettings.luminanceEdgeStoppingRelaxation =
        envF("NRD4_LUMRELAX", mRelaxSettings.luminanceEdgeStoppingRelaxation);
#else
    // Override some defaults coming from the NRD SDK.
    mRelaxDiffuseSpecularSettings.diffusePrepassBlurRadius = 16.0f;
    mRelaxDiffuseSpecularSettings.specularPrepassBlurRadius = 16.0f;
    mRelaxDiffuseSpecularSettings.diffuseMaxFastAccumulatedFrameNum = 2;
    mRelaxDiffuseSpecularSettings.specularMaxFastAccumulatedFrameNum = 2;
    mRelaxDiffuseSpecularSettings.diffuseLobeAngleFraction = 0.8f;
    mRelaxDiffuseSpecularSettings.disocclusionFixMaxRadius = 32.0f;
    mRelaxDiffuseSpecularSettings.enableSpecularVirtualHistoryClamping = false;
    mRelaxDiffuseSpecularSettings.disocclusionFixNumFramesToFix = 4;
    mRelaxDiffuseSpecularSettings.spatialVarianceEstimationHistoryThreshold = 4;
    mRelaxDiffuseSpecularSettings.atrousIterationNum = 6;
    mRelaxDiffuseSpecularSettings.depthThreshold = 0.02f;
    mRelaxDiffuseSpecularSettings.roughnessFraction = 0.5f;
    mRelaxDiffuseSpecularSettings.specularLobeAngleFraction = 0.9f;
    mRelaxDiffuseSpecularSettings.specularLobeAngleSlack = 10.0f;

    mRelaxDiffuseSettings.prepassBlurRadius = 16.0f;
    mRelaxDiffuseSettings.diffuseMaxFastAccumulatedFrameNum = 2;
    mRelaxDiffuseSettings.diffuseLobeAngleFraction = 0.8f;
    mRelaxDiffuseSettings.disocclusionFixMaxRadius = 32.0f;
    mRelaxDiffuseSettings.disocclusionFixNumFramesToFix = 4;
    mRelaxDiffuseSettings.spatialVarianceEstimationHistoryThreshold = 4;
    mRelaxDiffuseSettings.atrousIterationNum = 6;
    mRelaxDiffuseSettings.depthThreshold = 0.02f;
#endif

    // Deserialize pass from dictionary.
    for (const auto& [key, value] : props)
    {
        if (key == kEnabled)
            mEnabled = value;
        else if (key == kMethod)
            mDenoisingMethod = value;
        else if (key == kOutputSize)
            mOutputSizeSelection = value;

        // Common settings.
        else if (key == kWorldSpaceMotion)
            mWorldSpaceMotion = value;
        else if (key == kDisocclusionThreshold)
            mDisocclusionThreshold = value;

        // Pack radiance settings.
        else if (key == kMaxIntensity)
            mMaxIntensity = value;
#if FALCOR_HAS_NRD4
        else if (key == kShResolveMode)
            mShResolveMode = value;
        else if (key == kEnableValidation)
            mEnableValidation = value;
#endif

        // ReLAX diffuse/specular settings.
#if !FALCOR_HAS_NRD4
        // RELAX settings are not round-tripped under NRD v4: the three v3.1 structs were merged
        // into one RelaxSettings whose fields were renamed, retyped and re-defaulted (see
        // Source/RenderPasses/NRDPass/README.md). Silently accepting v3.1-era property names
        // would apply v3.1 tuning to a different filter, so they are rejected instead.
        else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
        {
            if (key == kDiffusePrepassBlurRadius)
                mRelaxDiffuseSpecularSettings.diffusePrepassBlurRadius = value;
            else if (key == kSpecularPrepassBlurRadius)
                mRelaxDiffuseSpecularSettings.specularPrepassBlurRadius = value;
            else if (key == kDiffuseMaxAccumulatedFrameNum)
                mRelaxDiffuseSpecularSettings.diffuseMaxAccumulatedFrameNum = value;
            else if (key == kSpecularMaxAccumulatedFrameNum)
                mRelaxDiffuseSpecularSettings.specularMaxAccumulatedFrameNum = value;
            else if (key == kDiffuseMaxFastAccumulatedFrameNum)
                mRelaxDiffuseSpecularSettings.diffuseMaxFastAccumulatedFrameNum = value;
            else if (key == kSpecularMaxFastAccumulatedFrameNum)
                mRelaxDiffuseSpecularSettings.specularMaxFastAccumulatedFrameNum = value;
            else if (key == kDiffusePhiLuminance)
                mRelaxDiffuseSpecularSettings.diffusePhiLuminance = value;
            else if (key == kSpecularPhiLuminance)
                mRelaxDiffuseSpecularSettings.specularPhiLuminance = value;
            else if (key == kDiffuseLobeAngleFraction)
                mRelaxDiffuseSpecularSettings.diffuseLobeAngleFraction = value;
            else if (key == kSpecularLobeAngleFraction)
                mRelaxDiffuseSpecularSettings.specularLobeAngleFraction = value;
            else if (key == kRoughnessFraction)
                mRelaxDiffuseSpecularSettings.roughnessFraction = value;
            else if (key == kDiffuseHistoryRejectionNormalThreshold)
                mRelaxDiffuseSpecularSettings.diffuseHistoryRejectionNormalThreshold = value;
            else if (key == kSpecularVarianceBoost)
                mRelaxDiffuseSpecularSettings.specularVarianceBoost = value;
            else if (key == kSpecularLobeAngleSlack)
                mRelaxDiffuseSpecularSettings.specularLobeAngleSlack = value;
            else if (key == kDisocclusionFixEdgeStoppingNormalPower)
                mRelaxDiffuseSpecularSettings.disocclusionFixEdgeStoppingNormalPower = value;
            else if (key == kDisocclusionFixMaxRadius)
                mRelaxDiffuseSpecularSettings.disocclusionFixMaxRadius = value;
            else if (key == kDisocclusionFixNumFramesToFix)
                mRelaxDiffuseSpecularSettings.disocclusionFixNumFramesToFix = value;
            else if (key == kHistoryClampingColorBoxSigmaScale)
                mRelaxDiffuseSpecularSettings.historyClampingColorBoxSigmaScale = value;
            else if (key == kSpatialVarianceEstimationHistoryThreshold)
                mRelaxDiffuseSpecularSettings.spatialVarianceEstimationHistoryThreshold = value;
            else if (key == kAtrousIterationNum)
                mRelaxDiffuseSpecularSettings.atrousIterationNum = value;
            else if (key == kMinLuminanceWeight)
                mRelaxDiffuseSpecularSettings.minLuminanceWeight = value;
            else if (key == kDepthThreshold)
                mRelaxDiffuseSpecularSettings.depthThreshold = value;
            else if (key == kLuminanceEdgeStoppingRelaxation)
                mRelaxDiffuseSpecularSettings.luminanceEdgeStoppingRelaxation = value;
            else if (key == kNormalEdgeStoppingRelaxation)
                mRelaxDiffuseSpecularSettings.normalEdgeStoppingRelaxation = value;
            else if (key == kRoughnessEdgeStoppingRelaxation)
                mRelaxDiffuseSpecularSettings.roughnessEdgeStoppingRelaxation = value;
            else if (key == kEnableAntiFirefly)
                mRelaxDiffuseSpecularSettings.enableAntiFirefly = value;
            else if (key == kEnableReprojectionTestSkippingWithoutMotion)
                mRelaxDiffuseSpecularSettings.enableReprojectionTestSkippingWithoutMotion = value;
            else if (key == kEnableSpecularVirtualHistoryClamping)
                mRelaxDiffuseSpecularSettings.enableSpecularVirtualHistoryClamping = value;
            else if (key == kEnableRoughnessEdgeStopping)
                mRelaxDiffuseSpecularSettings.enableRoughnessEdgeStopping = value;
            else if (key == kEnableMaterialTestForDiffuse)
                mRelaxDiffuseSpecularSettings.enableMaterialTestForDiffuse = value;
            else if (key == kEnableMaterialTestForSpecular)
                mRelaxDiffuseSpecularSettings.enableMaterialTestForSpecular = value;
            else
            {
                logWarning("Unknown property '{}' in NRD properties.", key);
            }
        }
        else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
        {
            if (key == kDiffusePrepassBlurRadius)
                mRelaxDiffuseSettings.prepassBlurRadius = value;
            else if (key == kDiffuseMaxAccumulatedFrameNum)
                mRelaxDiffuseSettings.diffuseMaxAccumulatedFrameNum = value;
            else if (key == kDiffuseMaxFastAccumulatedFrameNum)
                mRelaxDiffuseSettings.diffuseMaxFastAccumulatedFrameNum = value;
            else if (key == kDiffusePhiLuminance)
                mRelaxDiffuseSettings.diffusePhiLuminance = value;
            else if (key == kDiffuseLobeAngleFraction)
                mRelaxDiffuseSettings.diffuseLobeAngleFraction = value;
            else if (key == kDiffuseHistoryRejectionNormalThreshold)
                mRelaxDiffuseSettings.diffuseHistoryRejectionNormalThreshold = value;
            else if (key == kDisocclusionFixEdgeStoppingNormalPower)
                mRelaxDiffuseSettings.disocclusionFixEdgeStoppingNormalPower = value;
            else if (key == kDisocclusionFixMaxRadius)
                mRelaxDiffuseSettings.disocclusionFixMaxRadius = value;
            else if (key == kDisocclusionFixNumFramesToFix)
                mRelaxDiffuseSettings.disocclusionFixNumFramesToFix = value;
            else if (key == kHistoryClampingColorBoxSigmaScale)
                mRelaxDiffuseSettings.historyClampingColorBoxSigmaScale = value;
            else if (key == kSpatialVarianceEstimationHistoryThreshold)
                mRelaxDiffuseSettings.spatialVarianceEstimationHistoryThreshold = value;
            else if (key == kAtrousIterationNum)
                mRelaxDiffuseSettings.atrousIterationNum = value;
            else if (key == kMinLuminanceWeight)
                mRelaxDiffuseSettings.minLuminanceWeight = value;
            else if (key == kDepthThreshold)
                mRelaxDiffuseSettings.depthThreshold = value;
            else if (key == kEnableAntiFirefly)
                mRelaxDiffuseSettings.enableAntiFirefly = value;
            else if (key == kEnableReprojectionTestSkippingWithoutMotion)
                mRelaxDiffuseSettings.enableReprojectionTestSkippingWithoutMotion = value;
            else if (key == kEnableMaterialTestForDiffuse)
                mRelaxDiffuseSettings.enableMaterialTest = value;
            else
            {
                logWarning("Unknown property '{}' in NRD properties.", key);
            }
        }
#endif
        else
        {
            logWarning("Unknown property '{}' in NRD properties.", key);
        }
    }
}

Properties NRDPass::getProperties() const
{
    Properties props;

    props[kEnabled] = mEnabled;
    props[kMethod] = mDenoisingMethod;
    props[kOutputSize] = mOutputSizeSelection;

    // Common settings.
    props[kWorldSpaceMotion] = mWorldSpaceMotion;
    props[kDisocclusionThreshold] = mDisocclusionThreshold;

    // Pack radiance settings.
    props[kMaxIntensity] = mMaxIntensity;
#if FALCOR_HAS_NRD4
    props[kShResolveMode] = mShResolveMode;
    props[kEnableValidation] = mEnableValidation;
#endif
#if !FALCOR_HAS_NRD4

    // ReLAX diffuse/specular settings.
    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
    {
        props[kDiffusePrepassBlurRadius] = mRelaxDiffuseSpecularSettings.diffusePrepassBlurRadius;
        props[kSpecularPrepassBlurRadius] = mRelaxDiffuseSpecularSettings.specularPrepassBlurRadius;
        props[kDiffuseMaxAccumulatedFrameNum] = mRelaxDiffuseSpecularSettings.diffuseMaxAccumulatedFrameNum;
        props[kSpecularMaxAccumulatedFrameNum] = mRelaxDiffuseSpecularSettings.specularMaxAccumulatedFrameNum;
        props[kDiffuseMaxFastAccumulatedFrameNum] = mRelaxDiffuseSpecularSettings.diffuseMaxFastAccumulatedFrameNum;
        props[kSpecularMaxFastAccumulatedFrameNum] = mRelaxDiffuseSpecularSettings.specularMaxFastAccumulatedFrameNum;
        props[kDiffusePhiLuminance] = mRelaxDiffuseSpecularSettings.diffusePhiLuminance;
        props[kSpecularPhiLuminance] = mRelaxDiffuseSpecularSettings.specularPhiLuminance;
        props[kDiffuseLobeAngleFraction] = mRelaxDiffuseSpecularSettings.diffuseLobeAngleFraction;
        props[kSpecularLobeAngleFraction] = mRelaxDiffuseSpecularSettings.specularLobeAngleFraction;
        props[kRoughnessFraction] = mRelaxDiffuseSpecularSettings.roughnessFraction;
        props[kDiffuseHistoryRejectionNormalThreshold] = mRelaxDiffuseSpecularSettings.diffuseHistoryRejectionNormalThreshold;
        props[kSpecularVarianceBoost] = mRelaxDiffuseSpecularSettings.specularVarianceBoost;
        props[kSpecularLobeAngleSlack] = mRelaxDiffuseSpecularSettings.specularLobeAngleSlack;
        props[kDisocclusionFixEdgeStoppingNormalPower] = mRelaxDiffuseSpecularSettings.disocclusionFixEdgeStoppingNormalPower;
        props[kDisocclusionFixMaxRadius] = mRelaxDiffuseSpecularSettings.disocclusionFixMaxRadius;
        props[kDisocclusionFixNumFramesToFix] = mRelaxDiffuseSpecularSettings.disocclusionFixNumFramesToFix;
        props[kHistoryClampingColorBoxSigmaScale] = mRelaxDiffuseSpecularSettings.historyClampingColorBoxSigmaScale;
        props[kSpatialVarianceEstimationHistoryThreshold] = mRelaxDiffuseSpecularSettings.spatialVarianceEstimationHistoryThreshold;
        props[kAtrousIterationNum] = mRelaxDiffuseSpecularSettings.atrousIterationNum;
        props[kMinLuminanceWeight] = mRelaxDiffuseSpecularSettings.minLuminanceWeight;
        props[kDepthThreshold] = mRelaxDiffuseSpecularSettings.depthThreshold;
        props[kLuminanceEdgeStoppingRelaxation] = mRelaxDiffuseSpecularSettings.luminanceEdgeStoppingRelaxation;
        props[kNormalEdgeStoppingRelaxation] = mRelaxDiffuseSpecularSettings.normalEdgeStoppingRelaxation;
        props[kRoughnessEdgeStoppingRelaxation] = mRelaxDiffuseSpecularSettings.roughnessEdgeStoppingRelaxation;
        props[kEnableAntiFirefly] = mRelaxDiffuseSpecularSettings.enableAntiFirefly;
        props[kEnableReprojectionTestSkippingWithoutMotion] = mRelaxDiffuseSpecularSettings.enableReprojectionTestSkippingWithoutMotion;
        props[kEnableSpecularVirtualHistoryClamping] = mRelaxDiffuseSpecularSettings.enableSpecularVirtualHistoryClamping;
        props[kEnableRoughnessEdgeStopping] = mRelaxDiffuseSpecularSettings.enableRoughnessEdgeStopping;
        props[kEnableMaterialTestForDiffuse] = mRelaxDiffuseSpecularSettings.enableMaterialTestForDiffuse;
        props[kEnableMaterialTestForSpecular] = mRelaxDiffuseSpecularSettings.enableMaterialTestForSpecular;
    }
    else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
    {
        props[kDiffusePrepassBlurRadius] = mRelaxDiffuseSettings.prepassBlurRadius;
        props[kDiffuseMaxAccumulatedFrameNum] = mRelaxDiffuseSettings.diffuseMaxAccumulatedFrameNum;
        props[kDiffuseMaxFastAccumulatedFrameNum] = mRelaxDiffuseSettings.diffuseMaxFastAccumulatedFrameNum;
        props[kDiffusePhiLuminance] = mRelaxDiffuseSettings.diffusePhiLuminance;
        props[kDiffuseLobeAngleFraction] = mRelaxDiffuseSettings.diffuseLobeAngleFraction;
        props[kDiffuseHistoryRejectionNormalThreshold] = mRelaxDiffuseSettings.diffuseHistoryRejectionNormalThreshold;
        props[kDisocclusionFixEdgeStoppingNormalPower] = mRelaxDiffuseSettings.disocclusionFixEdgeStoppingNormalPower;
        props[kDisocclusionFixMaxRadius] = mRelaxDiffuseSettings.disocclusionFixMaxRadius;
        props[kDisocclusionFixNumFramesToFix] = mRelaxDiffuseSettings.disocclusionFixNumFramesToFix;
        props[kHistoryClampingColorBoxSigmaScale] = mRelaxDiffuseSettings.historyClampingColorBoxSigmaScale;
        props[kSpatialVarianceEstimationHistoryThreshold] = mRelaxDiffuseSettings.spatialVarianceEstimationHistoryThreshold;
        props[kAtrousIterationNum] = mRelaxDiffuseSettings.atrousIterationNum;
        props[kMinLuminanceWeight] = mRelaxDiffuseSettings.minLuminanceWeight;
        props[kDepthThreshold] = mRelaxDiffuseSettings.depthThreshold;
        props[kEnableAntiFirefly] = mRelaxDiffuseSettings.enableAntiFirefly;
        props[kEnableReprojectionTestSkippingWithoutMotion] = mRelaxDiffuseSettings.enableReprojectionTestSkippingWithoutMotion;
        props[kEnableMaterialTestForDiffuse] = mRelaxDiffuseSettings.enableMaterialTest;
    }
#endif

    return props;
}

RenderPassReflection NRDPass::reflect(const CompileData& compileData)
{
    RenderPassReflection reflector;

    const uint2 sz = RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mScreenSize, compileData.defaultTexDims);

    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
    {
        reflector.addInput(kInputDiffuseRadianceHitDist, "Diffuse radiance and hit distance");
        reflector.addInput(kInputSpecularRadianceHitDist, "Specular radiance and hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");

        reflector.addOutput(kOutputFilteredDiffuseRadianceHitDist, "Filtered diffuse radiance and hit distance")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
        reflector.addOutput(kOutputFilteredSpecularRadianceHitDist, "Filtered specular radiance and hit distance")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
    {
        reflector.addInput(kInputDiffuseRadianceHitDist, "Diffuse radiance and hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");

        reflector.addOutput(kOutputFilteredDiffuseRadianceHitDist, "Filtered diffuse radiance and hit distance")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::SpecularReflectionMv)
    {
        reflector.addInput(kInputSpecularHitDist, "Specular hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");

        reflector.addOutput(kOutputReflectionMotionVectors, "Reflection motion vectors in screen space")
            .format(ResourceFormat::RG16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::SpecularDeltaMv)
    {
        reflector.addInput(kInputDeltaPrimaryPosW, "Delta primary world position");
        reflector.addInput(kInputDeltaSecondaryPosW, "Delta secondary world position");
        reflector.addInput(kInputMotionVectors, "Motion vectors");

        reflector.addOutput(kOutputDeltaMotionVectors, "Delta motion vectors in screen space")
            .format(ResourceFormat::RG16Float)
            .texture2D(sz.x, sz.y);
    }
#if FALCOR_HAS_NRD4
    else if (mDenoisingMethod == DenoisingMethod::RelaxSpecular || mDenoisingMethod == DenoisingMethod::ReblurSpecular)
    {
        reflector.addInput(kInputSpecularRadianceHitDist, "Specular radiance and hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");
        reflector.addOutput(kOutputFilteredSpecularRadianceHitDist, "Filtered specular radiance and hit distance")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::ReblurDiffuse)
    {
        reflector.addInput(kInputDiffuseRadianceHitDist, "Diffuse radiance and hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");
        reflector.addOutput(kOutputFilteredDiffuseRadianceHitDist, "Filtered diffuse radiance and hit distance")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::ReblurDiffuseOcclusion)
    {
        // Occlusion variants carry NO radiance -- just a normalized hit distance in and out (AO).
        reflector.addInput(kInputDiffuseHitDist, "Diffuse normalized hit distance");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");
        reflector.addOutput(kOutputFilteredDiffuseHitDist, "Filtered diffuse normalized hit distance")
            .format(ResourceFormat::R16Float)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::SigmaShadow || mDenoisingMethod == DenoisingMethod::SigmaShadowTranslucency)
    {
        // SIGMA is a shadow denoiser: its input is penumbra size, not radiance. It ignores IN_MV when
        // stabilization is off, but the graph still declares it so one wiring serves both cases.
        reflector.addInput(kInputPenumbra, "Penumbra (SIGMA)");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");
        if (mDenoisingMethod == DenoisingMethod::SigmaShadowTranslucency)
            reflector.addInput(kInputTranslucency, "Translucency (SIGMA)");
        reflector.addOutput(kOutputShadowTranslucency, "Filtered shadow and translucency")
            .format(ResourceFormat::RGBA8Unorm)
            .texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::Reference)
    {
        // REFERENCE just accumulates. Per the Denoiser enum's own note it uses neither IN_MV,
        // IN_NORMAL_ROUGHNESS nor IN_VIEWZ, so declaring them would be a lie the graph has to satisfy.
        reflector.addInput(kInputSignal, "Signal to accumulate");
        reflector.addOutput(kOutputSignal, "Accumulated signal").format(ResourceFormat::RGBA16Float).texture2D(sz.x, sz.y);
    }
    else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSh || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSh)
    {
        // SH mode: a PAIR in and a pair out, instead of packed radiance+hitDist.
        reflector.addInput(kInputDiffuseSh0, "Diffuse SH0 (c0, chroma.xy, normHitDist)");
        reflector.addInput(kInputDiffuseSh1, "Diffuse SH1 (c1.xyz, sharpness)");
        reflector.addInput(kInputViewZ, "View Z");
        reflector.addInput(kInputNormalRoughnessMaterialID, "World normal, roughness, and material ID");
        reflector.addInput(kInputMotionVectors, "Motion vectors");
        // The SH pair is INTERNAL: NRD writes it, the resolve consumes it, and the pass emits ordinary
        // radiance on the same pin name the radiance path uses. Exposing coefficients as the pass
        // output would let ModulateIllumination multiply albedo into SH coefficients -- which yields
        // something that looks like an image and is not one.
        // NOT Optional, despite nothing downstream consuming them. NRD writes OUT_DIFF_SH0/SH1 and
        // the resolve reads them back, so they are scratch that must exist. Marking them optional
        // means the graph does not allocate them when unconsumed, and NRD then writes through a null
        // texture -- an access violation, not a diagnosable error. (The bypass path survived it only
        // because it resolves from the INPUT pair, which the adapter does connect.)
        reflector.addOutput(kOutputDiffuseSh0, "Filtered diffuse SH0 (internal scratch)")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
        reflector.addOutput(kOutputDiffuseSh1, "Filtered diffuse SH1 (internal scratch)")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
        reflector.addOutput(kOutputFilteredDiffuseRadianceHitDist, "Diffuse radiance resolved from SH")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y);
    }
#endif
    else
    {
        FALCOR_UNREACHABLE();
    }

#if FALCOR_HAS_NRD4
    // Optional inputs, shared by the radiance denoisers. Declared optional so an unconnected graph
    // still compiles; execute() tells NRD they exist only when they are actually bound, because
    // claiming an unbound confidence input reads as "confidence 0", not as an error.
    if (mDenoisingMethod != DenoisingMethod::Reference && mDenoisingMethod != DenoisingMethod::SigmaShadow &&
        mDenoisingMethod != DenoisingMethod::SigmaShadowTranslucency)
    {
        reflector.addInput(kInputDiffuseConfidence, "Diffuse history confidence (optional)").flags(RenderPassReflection::Field::Flags::Optional);
        reflector.addInput(kInputSpecularConfidence, "Specular history confidence (optional)").flags(RenderPassReflection::Field::Flags::Optional);
        reflector.addInput(kInputDisocclusionThresholdMix, "Disocclusion threshold mix (optional)")
            .flags(RenderPassReflection::Field::Flags::Optional);
    }

    // Only reflected when enabled: an always-present validation target would cost a full-resolution
    // RGBA8 allocation in every graph that never looks at it.
    if (mEnableValidation)
    {
        reflector.addOutput(kOutputValidation, "NRD validation overlay")
            .format(ResourceFormat::RGBA8Unorm)
            .texture2D(sz.x, sz.y);
    }
#endif

    return reflector;
}

void NRDPass::compile(RenderContext* pRenderContext, const CompileData& compileData)
{
    mScreenSize = RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mScreenSize, compileData.defaultTexDims);
    if (mScreenSize.x == 0 || mScreenSize.y == 0)
        mScreenSize = compileData.defaultTexDims;
    mFrameIndex = 0;
    reinit();
}

void NRDPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    if (!mpScene)
        return;

    bool enabled = false;
    enabled = mEnabled;

    if (enabled)
    {
        executeInternal(pRenderContext, renderData);
    }
    else
    {
        if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
        {
            pRenderContext->blit(
                renderData.getTexture(kInputDiffuseRadianceHitDist)->getSRV(),
                renderData.getTexture(kOutputFilteredDiffuseRadianceHitDist)->getRTV()
            );
            pRenderContext->blit(
                renderData.getTexture(kInputSpecularRadianceHitDist)->getSRV(),
                renderData.getTexture(kOutputFilteredSpecularRadianceHitDist)->getRTV()
            );
        }
#if FALCOR_HAS_NRD4
        else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSh || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSh)
        {
            // Bypassing the DENOISER must not bypass the resolve -- the output pin carries radiance
            // in this mode, so blitting coefficients into it would emit nonsense. Resolve straight
            // from the INPUT pair instead. That makes "enabled = false" an exact identity test of the
            // SH pack/resolve round trip, independent of NRD, which is the only way to tell a broken
            // transform apart from a badly-behaved denoiser.
            resolveSh(
                pRenderContext,
                renderData,
                renderData.getTexture(kInputDiffuseSh0),
                renderData.getTexture(kInputDiffuseSh1),
                renderData.getTexture(kOutputFilteredDiffuseRadianceHitDist),
                true // the adapter's pair is still linear RGB; NRD never ran to convert it
            );
        }
#endif
        else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
        {
            pRenderContext->blit(
                renderData.getTexture(kInputDiffuseRadianceHitDist)->getSRV(),
                renderData.getTexture(kOutputFilteredDiffuseRadianceHitDist)->getRTV()
            );
        }
        else if (mDenoisingMethod == DenoisingMethod::SpecularReflectionMv)
        {
            if (mWorldSpaceMotion)
            {
                pRenderContext->clearRtv(renderData.getTexture(kOutputReflectionMotionVectors)->getRTV().get(), float4(0.f));
            }
            else
            {
                pRenderContext->blit(
                    renderData.getTexture(kInputMotionVectors)->getSRV(), renderData.getTexture(kOutputReflectionMotionVectors)->getRTV()
                );
            }
        }
        else if (mDenoisingMethod == DenoisingMethod::SpecularDeltaMv)
        {
            if (mWorldSpaceMotion)
            {
                pRenderContext->clearRtv(renderData.getTexture(kOutputDeltaMotionVectors)->getRTV().get(), float4(0.f));
            }
            else
            {
                pRenderContext->blit(
                    renderData.getTexture(kInputMotionVectors)->getSRV(), renderData.getTexture(kOutputDeltaMotionVectors)->getRTV()
                );
            }
        }
    }
}

void NRDPass::renderUI(Gui::Widgets& widget)
{
#if FALCOR_HAS_NRD4
    const nrd::LibraryDesc& nrdLibraryDesc = *nrd::GetLibraryDesc();
#else
    const nrd::LibraryDesc& nrdLibraryDesc = nrd::GetLibraryDesc();
#endif
    char name[256];
    _snprintf_s(name, 255, "NRD Library v%u.%u.%u", nrdLibraryDesc.versionMajor, nrdLibraryDesc.versionMinor, nrdLibraryDesc.versionBuild);
    widget.text(name);

    widget.checkbox("Enabled", mEnabled);

    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
    {
        mRecreateDenoiser = widget.dropdown("Denoising method", kDenoisingMethod, reinterpret_cast<uint32_t&>(mDenoisingMethod));
    }

#if FALCOR_HAS_NRD4
    // v4 CommonSettings, shown for every method because they are method-independent.
    if (auto group = widget.group("Common (v4)"))
    {
        // clang-format off
        // Toggling validation changes what reflect() declares, so the graph has to be rebuilt --
        // without this the output would be requested and never allocated.
        if (group.checkbox("Validation overlay", mEnableValidation))
            requestRecompile();
        group.tooltip("Renders NRD's own debug view (viewZ, normals, motion, history length) to the 'validation' output.");
        group.slider("Split screen (noisy|denoised)", mSplitScreen, 0.0f, 1.0f, false, "%.2f");
        group.slider("Disocclusion threshold alt (%)", mDisocclusionThresholdAlternate, 0.0f, 20.0f, false, "%.2f");
        group.tooltip("Mixed in per-pixel via the optional 'disocclusionThresholdMix' input, or by strandMaterialID.");
        group.var("Strand thickness", mStrandThickness, 0.0f, 1.0f, 1e-5f, false, "%.5f");
        group.var("Strand material ID", mStrandMaterialID, 0.0f, 999.0f);
        group.var("Camera-attached refl. material ID", mCameraAttachedReflectionMaterialID, 0.0f, 999.0f);
        // clang-format on
    }

    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSh || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSh)
    {
        if (auto group = widget.group("SH resolve", true))
        {
            group.dropdown("Mode", mShResolveMode);
            group.tooltip(
                "Dc: DC term only -- correct for an isotropic phase function (g = 0), which is what "
                "this renderer's media use.\n"
                "Cosine: NRD_SH_ResolveDiffuse about the guide normal -- NVIDIA's intended usage, but "
                "a surface-shading model applied to a medium that has no surface."
            );
        }
    }
#endif

    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular)
    {
        widget.text("Common:");
        widget.text(mWorldSpaceMotion ? "Motion: world space" : "Motion: screen space");
        widget.slider("Disocclusion threshold (%)", mDisocclusionThreshold, 0.0f, 5.0f, false, "%.2f");

        widget.text("Pack radiance:");
        widget.slider("Max intensity", mMaxIntensity, 0.f, 100000.f, false, "%.0f");

#if FALCOR_HAS_NRD4
        // ReLAX settings (NRD v4: one RelaxSettings struct shared by all RELAX denoisers).
        if (auto group = widget.group("ReLAX (v4)"))
        {
            // clang-format off
            group.text("Reprojection:");
            group.slider("Diffuse max accumulated frames", mRelaxSettings.diffuseMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse responsive max accumulated frames", mRelaxSettings.diffuseMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular max accumulated frames", mRelaxSettings.specularMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular responsive max accumulated frames", mRelaxSettings.specularMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.text("Prepass:");
            group.slider("Diffuse blur radius", mRelaxSettings.diffusePrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.slider("Specular blur radius", mRelaxSettings.specularPrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.text("History fix (was 'disocclusion fix' in v3.1):");
            group.slider("Frames to fix", mRelaxSettings.historyFixFrameNum, 0u, 100u);
            // NOTE: a PIXEL STRIDE in v4, not the float radius v3.1 called disocclusionFixMaxRadius.
            group.slider("Base pixel stride", mRelaxSettings.historyFixBasePixelStride, 1u, 64u);
            group.slider("Edge stopping normal power", mRelaxSettings.historyFixEdgeStoppingNormalPower, 0.0f, 128.0f, false, "%.1f");
            group.text("Spatial filter:");
            group.slider("A-trous iterations", mRelaxSettings.atrousIterationNum, 2u, 8u);
            group.slider("Diffuse phi luminance", mRelaxSettings.diffusePhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Specular phi luminance", mRelaxSettings.specularPhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Lobe angle fraction", mRelaxSettings.lobeAngleFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Roughness fraction", mRelaxSettings.roughnessFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Depth threshold", mRelaxSettings.depthThreshold, 0.0f, 0.05f, false, "%.4f");
            group.text("New in v4:");
            // v3.1 exposed antifirefly for REBLUR only. Our input is 1-spp volumetric radiance full
            // of fireflies, so this is one of the reasons for the upgrade.
            group.checkbox("Anti-firefly", mRelaxSettings.enableAntiFirefly);
            group.slider("Min hit distance weight", mRelaxSettings.minHitDistanceWeight, 0.0f, 1.0f, false, "%.2f");
            renderHitDistReconstructionUI(group, mRelaxSettings.hitDistanceReconstructionMode);
            group.slider("Confidence: relaxation mult", mRelaxSettings.confidenceDrivenRelaxationMultiplier, 0.0f, 1.0f, false, "%.2f");
            group.slider("Confidence: luminance relax", mRelaxSettings.confidenceDrivenLuminanceEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Confidence: normal relax", mRelaxSettings.confidenceDrivenNormalEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Antilag acceleration", mRelaxSettings.antilagSettings.accelerationAmount, 0.0f, 1.0f, false, "%.2f");
            // clang-format on
        }
#else
        // ReLAX diffuse/specular settings.
        if (auto group = widget.group("ReLAX Diffuse/Specular"))
        {
            // clang-format off
            group.text("Prepass:");
            group.slider("Specular blur radius", mRelaxDiffuseSpecularSettings.specularPrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.slider("Diffuse blur radius", mRelaxDiffuseSpecularSettings.diffusePrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.text("Reprojection:");
            group.slider("Specular max accumulated frames", mRelaxDiffuseSpecularSettings.specularMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular responsive max accumulated frames", mRelaxDiffuseSpecularSettings.specularMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse max accumulated frames", mRelaxDiffuseSpecularSettings.diffuseMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse responsive max accumulated frames", mRelaxDiffuseSpecularSettings.diffuseMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular variance boost", mRelaxDiffuseSpecularSettings.specularVarianceBoost, 0.0f, 8.0f, false, "%.1f");
            group.slider("Diffuse history rejection normal threshold", mRelaxDiffuseSpecularSettings.diffuseHistoryRejectionNormalThreshold, 0.0f, 1.0f, false, "%.2f");
            group.checkbox("Reprojection test skipping without motion", mRelaxDiffuseSpecularSettings.enableReprojectionTestSkippingWithoutMotion);
            group.checkbox("Specular virtual history clamping", mRelaxDiffuseSpecularSettings.enableSpecularVirtualHistoryClamping);
            group.text("Disocclusion fix:");
            group.slider("Edge stopping normal power", mRelaxDiffuseSpecularSettings.disocclusionFixEdgeStoppingNormalPower, 0.0f, 128.0f, false, "%.1f");
            group.slider("Max kernel radius", mRelaxDiffuseSpecularSettings.disocclusionFixMaxRadius, 0.0f, 100.0f, false, "%.0f");
            group.slider("Frames to fix", (uint32_t&)mRelaxDiffuseSpecularSettings.disocclusionFixNumFramesToFix, 0u, 100u);
            group.text("History clamping & antilag:");
            group.slider("Color clamping sigma", mRelaxDiffuseSpecularSettings.historyClampingColorBoxSigmaScale, 0.0f, 10.0f, false, "%.1f");
            group.text("Spatial variance estimation:");
            group.slider("History threshold", (uint32_t&)mRelaxDiffuseSpecularSettings.spatialVarianceEstimationHistoryThreshold, 0u, 10u);
            group.text("Firefly filter:");
            group.checkbox("Enable firefly filter", (bool&)mRelaxDiffuseSpecularSettings.enableAntiFirefly);
            group.text("Spatial filter:");
            group.slider("A-trous iterations", (uint32_t&)mRelaxDiffuseSpecularSettings.atrousIterationNum, 2u, 8u);
            group.slider("Specular luminance weight (sigma scale)", mRelaxDiffuseSpecularSettings.specularPhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Diffuse luminance weight (sigma scale)", mRelaxDiffuseSpecularSettings.diffusePhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Min luminance weight", mRelaxDiffuseSpecularSettings.minLuminanceWeight, 0.0f, 1.0f, false, "%.2f");
            group.slider("Depth weight (relative fraction)", mRelaxDiffuseSpecularSettings.depthThreshold, 0.0f, 0.05f, false, "%.2f");
            group.slider("Roughness weight (relative fraction)", mRelaxDiffuseSpecularSettings.roughnessFraction, 0.0f, 2.0f, false, "%.2f");
            group.slider("Diffuse lobe angle fraction", mRelaxDiffuseSpecularSettings.diffuseLobeAngleFraction, 0.0f, 2.0f, false, "%.1f");
            group.slider("Specular loba angle fraction", mRelaxDiffuseSpecularSettings.specularLobeAngleFraction, 0.0f, 2.0f, false, "%.1f");
            group.slider("Specular normal weight (degrees of slack)", mRelaxDiffuseSpecularSettings.specularLobeAngleSlack, 0.0f, 180.0f, false, "%.0f");
            group.slider("Roughness relaxation", mRelaxDiffuseSpecularSettings.roughnessEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Normal relaxation", mRelaxDiffuseSpecularSettings.normalEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Luminance relaxation", mRelaxDiffuseSpecularSettings.luminanceEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.checkbox("Roughness edge stopping", mRelaxDiffuseSpecularSettings.enableRoughnessEdgeStopping);
            // clang-format on
        }
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
    {
        widget.text("Common:");
        widget.text(mWorldSpaceMotion ? "Motion: world space" : "Motion: screen space");
        widget.slider("Disocclusion threshold (%)", mDisocclusionThreshold, 0.0f, 5.0f, false, "%.2f");

        widget.text("Pack radiance:");
        widget.slider("Max intensity", mMaxIntensity, 0.f, 100000.f, false, "%.0f");

#if FALCOR_HAS_NRD4
        // ReLAX settings (NRD v4: one RelaxSettings struct shared by all RELAX denoisers).
        if (auto group = widget.group("ReLAX (v4)"))
        {
            // clang-format off
            group.text("Reprojection:");
            group.slider("Diffuse max accumulated frames", mRelaxSettings.diffuseMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse responsive max accumulated frames", mRelaxSettings.diffuseMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular max accumulated frames", mRelaxSettings.specularMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Specular responsive max accumulated frames", mRelaxSettings.specularMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.text("Prepass:");
            group.slider("Diffuse blur radius", mRelaxSettings.diffusePrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.slider("Specular blur radius", mRelaxSettings.specularPrepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.text("History fix (was 'disocclusion fix' in v3.1):");
            group.slider("Frames to fix", mRelaxSettings.historyFixFrameNum, 0u, 100u);
            // NOTE: a PIXEL STRIDE in v4, not the float radius v3.1 called disocclusionFixMaxRadius.
            group.slider("Base pixel stride", mRelaxSettings.historyFixBasePixelStride, 1u, 64u);
            group.slider("Edge stopping normal power", mRelaxSettings.historyFixEdgeStoppingNormalPower, 0.0f, 128.0f, false, "%.1f");
            group.text("Spatial filter:");
            group.slider("A-trous iterations", mRelaxSettings.atrousIterationNum, 2u, 8u);
            group.slider("Diffuse phi luminance", mRelaxSettings.diffusePhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Specular phi luminance", mRelaxSettings.specularPhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Lobe angle fraction", mRelaxSettings.lobeAngleFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Roughness fraction", mRelaxSettings.roughnessFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Depth threshold", mRelaxSettings.depthThreshold, 0.0f, 0.05f, false, "%.4f");
            group.text("New in v4:");
            // v3.1 exposed antifirefly for REBLUR only. Our input is 1-spp volumetric radiance full
            // of fireflies, so this is one of the reasons for the upgrade.
            group.checkbox("Anti-firefly", mRelaxSettings.enableAntiFirefly);
            group.slider("Min hit distance weight", mRelaxSettings.minHitDistanceWeight, 0.0f, 1.0f, false, "%.2f");
            renderHitDistReconstructionUI(group, mRelaxSettings.hitDistanceReconstructionMode);
            group.slider("Confidence: relaxation mult", mRelaxSettings.confidenceDrivenRelaxationMultiplier, 0.0f, 1.0f, false, "%.2f");
            group.slider("Confidence: luminance relax", mRelaxSettings.confidenceDrivenLuminanceEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Confidence: normal relax", mRelaxSettings.confidenceDrivenNormalEdgeStoppingRelaxation, 0.0f, 1.0f, false, "%.2f");
            group.slider("Antilag acceleration", mRelaxSettings.antilagSettings.accelerationAmount, 0.0f, 1.0f, false, "%.2f");
            // clang-format on
        }
#else
        // ReLAX diffuse settings.
        if (auto group = widget.group("ReLAX Diffuse"))
        {
            // clang-format off
            group.text("Prepass:");
            group.slider("Diffuse blur radius", mRelaxDiffuseSettings.prepassBlurRadius, 0.0f, 100.0f, false, "%.0f");
            group.text("Reprojection:");
            group.slider("Diffuse max accumulated frames", mRelaxDiffuseSettings.diffuseMaxAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse responsive max accumulated frames", mRelaxDiffuseSettings.diffuseMaxFastAccumulatedFrameNum, 0u, nrd::RELAX_MAX_HISTORY_FRAME_NUM);
            group.slider("Diffuse history rejection normal threshold", mRelaxDiffuseSettings.diffuseHistoryRejectionNormalThreshold, 0.0f, 1.0f, false, "%.2f");
            group.checkbox("Reprojection test skipping without motion", mRelaxDiffuseSettings.enableReprojectionTestSkippingWithoutMotion);
            group.text("Disocclusion fix:");
            group.slider("Edge stopping normal power", mRelaxDiffuseSettings.disocclusionFixEdgeStoppingNormalPower, 0.0f, 128.0f, false, "%.1f");
            group.slider("Max kernel radius", mRelaxDiffuseSettings.disocclusionFixMaxRadius, 0.0f, 100.0f, false, "%.0f");
            group.slider("Frames to fix", (uint32_t&)mRelaxDiffuseSettings.disocclusionFixNumFramesToFix, 0u, 100u);
            group.text("History clamping & antilag:");
            group.slider("Color clamping sigma", mRelaxDiffuseSettings.historyClampingColorBoxSigmaScale, 0.0f, 10.0f, false, "%.1f");
            group.text("Spatial variance estimation:");
            group.slider("History threshold", (uint32_t&)mRelaxDiffuseSettings.spatialVarianceEstimationHistoryThreshold, 0u, 10u);
            group.text("Firefly filter:");
            group.checkbox("Enable firefly filter", (bool&)mRelaxDiffuseSettings.enableAntiFirefly);
            group.text("Spatial filter:");
            group.slider("A-trous iterations", (uint32_t&)mRelaxDiffuseSettings.atrousIterationNum, 2u, 8u);
            group.slider("Diffuse luminance weight (sigma scale)", mRelaxDiffuseSettings.diffusePhiLuminance, 0.0f, 10.0f, false, "%.1f");
            group.slider("Min luminance weight", mRelaxDiffuseSettings.minLuminanceWeight, 0.0f, 1.0f, false, "%.2f");
            group.slider("Depth weight (relative fraction)", mRelaxDiffuseSettings.depthThreshold, 0.0f, 0.05f, false, "%.2f");
            group.slider("Diffuse lobe angle fraction", mRelaxDiffuseSettings.diffuseLobeAngleFraction, 0.0f, 2.0f, false, "%.1f");
            // clang-format on
        }
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
    {
        widget.text("Common:");
        widget.text(mWorldSpaceMotion ? "Motion: world space" : "Motion: screen space");
        widget.slider("Disocclusion threshold (%)", mDisocclusionThreshold, 0.0f, 5.0f, false, "%.2f");

        widget.text("Pack radiance:");
        widget.slider("Max intensity", mMaxIntensity, 0.f, 100000.f, false, "%.0f");

#if FALCOR_HAS_NRD4
        if (auto group = widget.group("ReBLUR Diffuse/Specular (v4)"))
        {
            // clang-format off
            const float kEpsilon = 0.0001f;
            // v4 dropped SpecularLobeTrimmingParameters entirely, and hitDistanceParameters lost
            // its D term (the normalization curve changed: lerp(1,C,exp2(D*r^2)) -> lerp(C,1,smc)).
            if (auto group2 = group.group("Hit distance parameters"))
            {
                group2.slider("A", mReblurSettings.hitDistanceParameters.A, kEpsilon, 256.0f, false, "%.2f");
                group2.slider("B", mReblurSettings.hitDistanceParameters.B, kEpsilon, 256.0f, false, "%.2f");
                group2.slider("C", mReblurSettings.hitDistanceParameters.C, 1.0f, 256.0f, false, "%.2f");
            }
            // The two v3.1 antilag structs collapsed into one, and there is no longer any way to
            // disable antilag.
            if (auto group2 = group.group("Antilag"))
            {
                group2.slider("Luminance sigma scale", mReblurSettings.antilagSettings.luminanceSigmaScale, kEpsilon, 10.0f, false, "%.1f");
                group2.slider("Luminance sensitivity", mReblurSettings.antilagSettings.luminanceSensitivity, kEpsilon, 10.0f, false, "%.1f");
            }
            group.text("Accumulation:");
            group.slider("Max accumulated frames", mReblurSettings.maxAccumulatedFrameNum, 0u, nrd::REBLUR_MAX_HISTORY_FRAME_NUM);
            group.slider("Max fast accumulated frames", mReblurSettings.maxFastAccumulatedFrameNum, 0u, nrd::REBLUR_MAX_HISTORY_FRAME_NUM);
            // v3.1's stabilizationStrength was a normalized percentage; v4 counts frames instead.
            group.slider("Max stabilized frames", mReblurSettings.maxStabilizedFrameNum, 0u, nrd::REBLUR_MAX_HISTORY_FRAME_NUM);
            group.text("Spatial filter:");
            group.slider("Min blur radius", mReblurSettings.minBlurRadius, 0.0f, 100.0f, false, "%.1f");
            group.slider("Max blur radius", mReblurSettings.maxBlurRadius, 0.0f, 100.0f, false, "%.1f");
            group.slider("Lobe angle fraction", mReblurSettings.lobeAngleFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Roughness fraction", mReblurSettings.roughnessFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Plane distance sensitivity", mReblurSettings.planeDistanceSensitivity, 0.0f, 1.0f, false, "%.3f");
            group.text("History fix:");
            group.slider("Frames to fix", mReblurSettings.historyFixFrameNum, 0u, 100u);
            group.slider("Base pixel stride", mReblurSettings.historyFixBasePixelStride, 1u, 64u);
            group.text("Other:");
            group.checkbox("Anti-firefly", mReblurSettings.enableAntiFirefly);
            renderHitDistReconstructionUI(group, mReblurSettings.hitDistanceReconstructionMode);
            // New in v4.17. REBLUR drives denoising with f = 1/(1 + k*N); before 4.17 k was implicitly
            // 1, and 4.17 made it k = s * lerp(b, 1, ...). The defaults therefore CHANGE behaviour
            // versus every earlier REBLUR result -- s = 1, b = 1 restores it. Exposed rather than
            // hidden so a REBLUR comparison against older numbers can be made like-for-like.
            if (auto group2 = group.group("Convergence (v4.17)"))
            {
                group2.slider("s (overall scale)", mReblurSettings.convergenceSettings.s, 0.01f, 4.0f, false, "%.2f");
                group2.slider("b (short history)", mReblurSettings.convergenceSettings.b, 0.0f, 1.0f, false, "%.2f");
                group2.tooltip("s = 1, b = 1 reproduces pre-4.17 REBLUR behaviour.");
            }
            // clang-format on
        }
#else
        if (auto group = widget.group("ReBLUR Diffuse/Specular"))
        {
            // clang-format off
            const float kEpsilon = 0.0001f;
            if (auto group2 = group.group("Specular lobe trimming"))
            {
                group2.slider("A", mReblurSettings.specularLobeTrimmingParameters.A, -256.0f, 256.0f, false, "%.2f");
                group2.slider("B", mReblurSettings.specularLobeTrimmingParameters.B, kEpsilon, 256.0f, false, "%.2f");
                group2.slider("C", mReblurSettings.specularLobeTrimmingParameters.C, 1.0f, 256.0f, false, "%.2f");
            }

            if (auto group2 = group.group("Hit distance"))
            {
                group2.slider("A", mReblurSettings.hitDistanceParameters.A, -256.0f, 256.0f, false, "%.2f");
                group2.slider("B", mReblurSettings.hitDistanceParameters.B, kEpsilon, 256.0f, false, "%.2f");
                group2.slider("C", mReblurSettings.hitDistanceParameters.C, 1.0f, 256.0f, false, "%.2f");
                group2.slider("D", mReblurSettings.hitDistanceParameters.D, -256.0f, 0.0f, false, "%.2f");
            }

            if (auto group2 = group.group("Antilag intensity"))
            {
                group2.slider("Threshold min", mReblurSettings.antilagIntensitySettings.thresholdMin, 0.0f, 1.0f, false, "%.2f");
                group2.slider("Threshold max", mReblurSettings.antilagIntensitySettings.thresholdMax, 0.0f, 1.0f, false, "%.2f");
                group2.slider("Sigma scale", mReblurSettings.antilagIntensitySettings.sigmaScale, kEpsilon, 16.0f, false, "%.2f");
                group2.slider("Sensitivity to darkness", mReblurSettings.antilagIntensitySettings.sensitivityToDarkness, kEpsilon, 256.0f, false, "%.2f");
                group2.checkbox("Enable", mReblurSettings.antilagIntensitySettings.enable);
            }

            if (auto group2 = group.group("Antilag hit distance"))
            {
                group2.slider("Threshold min", mReblurSettings.antilagHitDistanceSettings.thresholdMin, 0.0f, 1.0f, false, "%.2f");
                group2.slider("Threshold max", mReblurSettings.antilagHitDistanceSettings.thresholdMax, 0.0f, 1.0f, false, "%.2f");
                group2.slider("Sigma scale", mReblurSettings.antilagHitDistanceSettings.sigmaScale, kEpsilon, 16.0f, false, "%.2f");
                group2.slider("Sensitivity to darkness", mReblurSettings.antilagHitDistanceSettings.sensitivityToDarkness, kEpsilon, 1.0f, false, "%.2f");
                group2.checkbox("Enable", mReblurSettings.antilagHitDistanceSettings.enable);
            }

            group.slider("Max accumulated frame num", mReblurSettings.maxAccumulatedFrameNum, 0u, nrd::REBLUR_MAX_HISTORY_FRAME_NUM);
            group.slider("Blur radius", mReblurSettings.blurRadius, 0.0f, 256.0f, false, "%.2f");
            group.slider("Min converged state base radius scale", mReblurSettings.minConvergedStateBaseRadiusScale, 0.0f, 1.0f, false, "%.2f");
            group.slider("Max adaptive radius scale", mReblurSettings.maxAdaptiveRadiusScale, 0.0f, 10.0f, false, "%.2f");
            group.slider("Normal weight (fraction of lobe)", mReblurSettings.lobeAngleFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Roughness weight (fraction)", mReblurSettings.roughnessFraction, 0.0f, 1.0f, false, "%.2f");
            group.slider("Responsive accumulation roughness threshold", mReblurSettings.responsiveAccumulationRoughnessThreshold, 0.0f, 1.0f, false, "%.2f");
            group.slider("Stabilization strength", mReblurSettings.stabilizationStrength, 0.0f, 1.0f, false, "%.2f");
            group.slider("History fix strength", mReblurSettings.historyFixStrength, 0.0f, 1.0f, false, "%.2f");
            group.slider("Plane distance sensitivity", mReblurSettings.planeDistanceSensitivity, kEpsilon, 16.0f, false, "%.3f");
            group.slider("Input mix", mReblurSettings.inputMix, 0.0f, 1.0f, false, "%.2f");
            group.slider("Residual noise level", mReblurSettings.residualNoiseLevel, 0.01f, 0.1f, false, "%.2f");
            group.checkbox("Antifirefly", mReblurSettings.enableAntiFirefly);
            group.checkbox("Reference accumulation", mReblurSettings.enableReferenceAccumulation);
            group.checkbox("Performance mode", mReblurSettings.enablePerformanceMode);
            group.checkbox("Material test for diffuse", mReblurSettings.enableMaterialTestForDiffuse);
            group.checkbox("Material test for specular", mReblurSettings.enableMaterialTestForSpecular);
            // clang-format on
        }
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::SpecularReflectionMv)
    {
        widget.text(mWorldSpaceMotion ? "Motion: world space" : "Motion: screen space");
    }
    else if (mDenoisingMethod == DenoisingMethod::SpecularDeltaMv)
    {
        widget.text(mWorldSpaceMotion ? "Motion: world space" : "Motion: screen space");
    }
}

void NRDPass::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    mpScene = pScene;
}

// NRD_CALL matters: v3.1 defined it as __fastcall, v4 as __stdcall, and v4 decorates the callback
// pointers with it. An undecorated callback compiles and then corrupts the stack on the first
// allocation, so the macro must be used rather than relying on the default convention.
static void* NRD_CALL nrdAllocate(void* userArg, size_t size, size_t alignment)
{
    return malloc(size);
}

static void* NRD_CALL nrdReallocate(void* userArg, void* memory, size_t size, size_t alignment)
{
    return realloc(memory, size);
}

static void NRD_CALL nrdFree(void* userArg, void* memory)
{
    free(memory);
}

static ResourceFormat getFalcorFormat(nrd::Format format)
{
    switch (format)
    {
    case nrd::Format::R8_UNORM:
        return ResourceFormat::R8Unorm;
    case nrd::Format::R8_SNORM:
        return ResourceFormat::R8Snorm;
    case nrd::Format::R8_UINT:
        return ResourceFormat::R8Uint;
    case nrd::Format::R8_SINT:
        return ResourceFormat::R8Int;
    case nrd::Format::RG8_UNORM:
        return ResourceFormat::RG8Unorm;
    case nrd::Format::RG8_SNORM:
        return ResourceFormat::RG8Snorm;
    case nrd::Format::RG8_UINT:
        return ResourceFormat::RG8Uint;
    case nrd::Format::RG8_SINT:
        return ResourceFormat::RG8Int;
    case nrd::Format::RGBA8_UNORM:
        return ResourceFormat::RGBA8Unorm;
    case nrd::Format::RGBA8_SNORM:
        return ResourceFormat::RGBA8Snorm;
    case nrd::Format::RGBA8_UINT:
        return ResourceFormat::RGBA8Uint;
    case nrd::Format::RGBA8_SINT:
        return ResourceFormat::RGBA8Int;
    case nrd::Format::RGBA8_SRGB:
        return ResourceFormat::RGBA8UnormSrgb;
    case nrd::Format::R16_UNORM:
        return ResourceFormat::R16Unorm;
    case nrd::Format::R16_SNORM:
        return ResourceFormat::R16Snorm;
    case nrd::Format::R16_UINT:
        return ResourceFormat::R16Uint;
    case nrd::Format::R16_SINT:
        return ResourceFormat::R16Int;
    case nrd::Format::R16_SFLOAT:
        return ResourceFormat::R16Float;
    case nrd::Format::RG16_UNORM:
        return ResourceFormat::RG16Unorm;
    case nrd::Format::RG16_SNORM:
        return ResourceFormat::RG16Snorm;
    case nrd::Format::RG16_UINT:
        return ResourceFormat::RG16Uint;
    case nrd::Format::RG16_SINT:
        return ResourceFormat::RG16Int;
    case nrd::Format::RG16_SFLOAT:
        return ResourceFormat::RG16Float;
    case nrd::Format::RGBA16_UNORM:
        return ResourceFormat::RGBA16Unorm;
    case nrd::Format::RGBA16_SNORM:
        return ResourceFormat::Unknown; // Not defined in Falcor
    case nrd::Format::RGBA16_UINT:
        return ResourceFormat::RGBA16Uint;
    case nrd::Format::RGBA16_SINT:
        return ResourceFormat::RGBA16Int;
    case nrd::Format::RGBA16_SFLOAT:
        return ResourceFormat::RGBA16Float;
    case nrd::Format::R32_UINT:
        return ResourceFormat::R32Uint;
    case nrd::Format::R32_SINT:
        return ResourceFormat::R32Int;
    case nrd::Format::R32_SFLOAT:
        return ResourceFormat::R32Float;
    case nrd::Format::RG32_UINT:
        return ResourceFormat::RG32Uint;
    case nrd::Format::RG32_SINT:
        return ResourceFormat::RG32Int;
    case nrd::Format::RG32_SFLOAT:
        return ResourceFormat::RG32Float;
    case nrd::Format::RGB32_UINT:
        return ResourceFormat::RGB32Uint;
    case nrd::Format::RGB32_SINT:
        return ResourceFormat::RGB32Int;
    case nrd::Format::RGB32_SFLOAT:
        return ResourceFormat::RGB32Float;
    case nrd::Format::RGBA32_UINT:
        return ResourceFormat::RGBA32Uint;
    case nrd::Format::RGBA32_SINT:
        return ResourceFormat::RGBA32Int;
    case nrd::Format::RGBA32_SFLOAT:
        return ResourceFormat::RGBA32Float;
    case nrd::Format::R10_G10_B10_A2_UNORM:
        return ResourceFormat::RGB10A2Unorm;
    case nrd::Format::R10_G10_B10_A2_UINT:
        return ResourceFormat::RGB10A2Uint;
    case nrd::Format::R11_G11_B10_UFLOAT:
        return ResourceFormat::R11G11B10Float;
    case nrd::Format::R9_G9_B9_E5_UFLOAT:
        return ResourceFormat::RGB9E5Float;
    default:
        FALCOR_THROW("Unsupported NRD format.");
    }
}

#if FALCOR_HAS_NRD4
// v4 renamed the enum Method -> Denoiser, reordered the families (so every RELAX/SIGMA/REFERENCE
// ordinal shifted), and DELETED SpecularReflectionMv / SpecularDeltaMv along with their settings
// structs and OUT_REFLECTION_MV / OUT_DELTA_MV / IN_DELTA_*_POS resource types. Those two methods
// therefore cannot exist under v4 -- select them and the pass throws rather than silently denoising
// something else. Use the v3.1 SDK if you need them (see scripts/PathTracerNRD.py).
static nrd::Denoiser getNrdMethod(NRDPass::DenoisingMethod denoisingMethod)
{
    switch (denoisingMethod)
    {
    case NRDPass::DenoisingMethod::RelaxDiffuseSpecular:
        return nrd::Denoiser::RELAX_DIFFUSE_SPECULAR;
    case NRDPass::DenoisingMethod::RelaxDiffuse:
        return nrd::Denoiser::RELAX_DIFFUSE;
    case NRDPass::DenoisingMethod::ReblurDiffuseSpecular:
        return nrd::Denoiser::REBLUR_DIFFUSE_SPECULAR;
    case NRDPass::DenoisingMethod::RelaxSpecular:
        return nrd::Denoiser::RELAX_SPECULAR;
    case NRDPass::DenoisingMethod::ReblurDiffuse:
        return nrd::Denoiser::REBLUR_DIFFUSE;
    case NRDPass::DenoisingMethod::ReblurSpecular:
        return nrd::Denoiser::REBLUR_SPECULAR;
    case NRDPass::DenoisingMethod::ReblurDiffuseOcclusion:
        return nrd::Denoiser::REBLUR_DIFFUSE_OCCLUSION;
    case NRDPass::DenoisingMethod::SigmaShadow:
        return nrd::Denoiser::SIGMA_SHADOW;
    case NRDPass::DenoisingMethod::SigmaShadowTranslucency:
        return nrd::Denoiser::SIGMA_SHADOW_TRANSLUCENCY;
    case NRDPass::DenoisingMethod::Reference:
        return nrd::Denoiser::REFERENCE;
    case NRDPass::DenoisingMethod::RelaxDiffuseSh:
        return nrd::Denoiser::RELAX_DIFFUSE_SH;
    case NRDPass::DenoisingMethod::ReblurDiffuseSh:
        return nrd::Denoiser::REBLUR_DIFFUSE_SH;
    case NRDPass::DenoisingMethod::SpecularReflectionMv:
    case NRDPass::DenoisingMethod::SpecularDeltaMv:
        FALCOR_THROW(
            "NRDPass: SpecularReflectionMv / SpecularDeltaMv were removed in NRD v4 and have no "
            "replacement. Build with FALCOR_USE_NRD4=OFF to use them."
        );
    default:
        FALCOR_UNREACHABLE();
        return nrd::Denoiser::RELAX_DIFFUSE_SPECULAR;
    }
}
#else
static nrd::Method getNrdMethod(NRDPass::DenoisingMethod denoisingMethod)
{
    switch (denoisingMethod)
    {
    case NRDPass::DenoisingMethod::RelaxDiffuseSpecular:
        return nrd::Method::RELAX_DIFFUSE_SPECULAR;
    case NRDPass::DenoisingMethod::RelaxDiffuse:
        return nrd::Method::RELAX_DIFFUSE;
    case NRDPass::DenoisingMethod::ReblurDiffuseSpecular:
        return nrd::Method::REBLUR_DIFFUSE_SPECULAR;
    case NRDPass::DenoisingMethod::SpecularReflectionMv:
        return nrd::Method::SPECULAR_REFLECTION_MV;
    case NRDPass::DenoisingMethod::SpecularDeltaMv:
        return nrd::Method::SPECULAR_DELTA_MV;
    default:
        // The v4-only methods land here. FALCOR_UNREACHABLE alone would fall through to
        // RELAX_DIFFUSE_SPECULAR in release, i.e. run a DIFFERENT denoiser than the one asked for and
        // report nothing -- so name the problem instead.
        FALCOR_THROW(
            "NRDPass: denoising method {} exists only in NRD v4. Configure with FALCOR_USE_NRD4=ON.",
            uint32_t(denoisingMethod)
        );
    }
}
#endif

/// Copies into col-major layout, as the NRD library works in column major layout,
/// while Falcor uses row-major layout
static void copyMatrix(float* dstMatrix, const float4x4& srcMatrix)
{
    float4x4 col_major = transpose(srcMatrix);
    memcpy(dstMatrix, static_cast<const float*>(col_major.data()), sizeof(float4x4));
}

void NRDPass::reinit()
{
#if FALCOR_HAS_NRD4
    // Destroy before recreating. The v3.1 path below simply nulled the handle, which leaked the
    // whole denoiser (including its texture pool) on every graph recompile.
    if (mpInstance)
    {
        nrd::DestroyInstance(*mpInstance);
        mpInstance = nullptr;
    }

    // The library's normal/roughness encoding is baked in at build time in v4 and cannot be
    // overridden per instance. If the vendored binary were built for a different encoding than the
    // one we compile the shaders with and NRDAdapter packs, IN_NORMAL_ROUGHNESS would be silently
    // misinterpreted rather than rejected -- a uniformly smeared frame and no error. Check rather
    // than assume; v3.1 accepted either encoding, v4 does not.
    //
    // Compared against kNrd*Encoding (not against a literal) so that editing the constants used for
    // the shader defines cannot drift away from the check that is supposed to police them.
    const nrd::LibraryDesc* pLibraryDesc = nrd::GetLibraryDesc();
    FALCOR_CHECK(pLibraryDesc != nullptr, "NRDPass: nrd::GetLibraryDesc() returned null.");
    FALCOR_CHECK(
        uint32_t(pLibraryDesc->normalEncoding) == kNrdNormalEncoding,
        "NRDPass: NRD was built for normal encoding {} but the shaders and NRDAdapter use {} "
        "(R10_G10_B10_A2_UNORM). Rebuild NRD or change kNrdNormalEncoding and "
        "NRDAdapter.cs.slang::encodeNormalRoughness together.",
        uint32_t(pLibraryDesc->normalEncoding),
        kNrdNormalEncoding
    );
    FALCOR_CHECK(
        uint32_t(pLibraryDesc->roughnessEncoding) == kNrdRoughnessEncoding,
        "NRDPass: NRD was built for roughness encoding {} but the shaders use {} (LINEAR). A mismatch "
        "here rescales roughness silently -- it does not error.",
        uint32_t(pLibraryDesc->roughnessEncoding),
        kNrdRoughnessEncoding
    );

    // Resolution is NOT passed at creation in v4 -- it lives in CommonSettings and can change per
    // frame, which is why this only names the denoiser.
    const nrd::DenoiserDesc denoisers[] = {{kDenoiserIdentifier, getNrdMethod(mDenoisingMethod)}};

    nrd::InstanceCreationDesc instanceCreationDesc = {};
    instanceCreationDesc.allocationCallbacks.Allocate = nrdAllocate;
    instanceCreationDesc.allocationCallbacks.Reallocate = nrdReallocate;
    instanceCreationDesc.allocationCallbacks.Free = nrdFree;
    instanceCreationDesc.denoisers = denoisers;
    instanceCreationDesc.denoisersNum = 1;

    nrd::Result res = nrd::CreateInstance(instanceCreationDesc, mpInstance);

    if (res != nrd::Result::SUCCESS)
        FALCOR_THROW("NRDPass: Failed to create NRD instance (result {}).", uint32_t(res));

    // Force the pool to be (re)built for the current size on the next createResources().
    mPoolResourceSize = {};
#else
    // Create a new denoiser instance.
    mpDenoiser = nullptr;

    const nrd::LibraryDesc& libraryDesc = nrd::GetLibraryDesc();

    const nrd::MethodDesc methods[] = {{getNrdMethod(mDenoisingMethod), uint16_t(mScreenSize.x), uint16_t(mScreenSize.y)}};

    nrd::DenoiserCreationDesc denoiserCreationDesc;
    denoiserCreationDesc.memoryAllocatorInterface.Allocate = nrdAllocate;
    denoiserCreationDesc.memoryAllocatorInterface.Reallocate = nrdReallocate;
    denoiserCreationDesc.memoryAllocatorInterface.Free = nrdFree;
    denoiserCreationDesc.requestedMethodNum = 1;
    denoiserCreationDesc.requestedMethods = methods;

    nrd::Result res = nrd::CreateDenoiser(denoiserCreationDesc, mpDenoiser);

    if (res != nrd::Result::SUCCESS)
        FALCOR_THROW("NRDPass: Failed to create NRD denoiser");
#endif

    createResources();
    createPipelines();
}

void NRDPass::createPipelines()
{
    mpPasses.clear();
    mpCachedProgramKernels.clear();
    mpCSOs.clear();
    mCBVSRVUAVdescriptorSetLayouts.clear();
    mpRootSignatures.clear();

#if FALCOR_HAS_NRD4
    const nrd::InstanceDesc& denoiserDesc = *nrd::GetInstanceDesc(*mpInstance);

    // v4 drops StaticSamplerDesc: samplers sit at consecutive registers from samplersBaseRegisterIndex.
    D3D12DescriptorSetLayout SamplersDescriptorSetLayout;
    for (uint32_t j = 0; j < denoiserDesc.samplersNum; j++)
    {
        SamplersDescriptorSetLayout.addRange(
            ShaderResourceType::Sampler, denoiserDesc.samplersBaseRegisterIndex + j, 1,
            denoiserDesc.constantBufferAndSamplersSpaceIndex
        );
    }
    mpSamplersDescriptorSet =
        D3D12DescriptorSet::create(mpDevice, SamplersDescriptorSetLayout, D3D12DescriptorSetBindingUsage::ExplicitBind);

    for (uint32_t j = 0; j < denoiserDesc.samplersNum; j++)
    {
        mpSamplersDescriptorSet->setSampler(0, j, mpSamplers[j].get());
    }

    for (uint32_t i = 0; i < denoiserDesc.pipelinesNum; i++)
    {
        const nrd::PipelineDesc& nrdPipelineDesc = denoiserDesc.pipelines[i];

        D3D12DescriptorSetLayout CBVSRVUAVdescriptorSetLayout;
        CBVSRVUAVdescriptorSetLayout.addRange(
            ShaderResourceType::Cbv, denoiserDesc.constantBufferRegisterIndex, 1, denoiserDesc.constantBufferAndSamplersSpaceIndex
        );

        // v4 removed ResourceRangeDesc::baseRegisterIndex, so registers must be derived. They run
        // consecutively from resourcesBaseRegisterIndex, but SRVs (t#) and UAVs (u#) are SEPARATE
        // register classes that each restart at the base -- see any *.resources.hlsli, e.g. RELAX
        // TemporalAccumulation binds t0..t12 alongside u0..u2. A single shared counter puts the UAV
        // range at u13, and D3D12 then rejects the pipeline with E_INVALIDARG because the root
        // signature does not cover the u0..u2 the shader actually declares.
        uint32_t srvRegisterOffset = 0;
        uint32_t uavRegisterOffset = 0;
        for (uint32_t j = 0; j < nrdPipelineDesc.resourceRangesNum; j++)
        {
            const nrd::ResourceRangeDesc& nrdDescriptorRange = nrdPipelineDesc.resourceRanges[j];

            const bool isSrv = nrdDescriptorRange.descriptorType == nrd::DescriptorType::TEXTURE;
            ShaderResourceType descriptorType = isSrv ? ShaderResourceType::TextureSrv : ShaderResourceType::TextureUav;
            uint32_t& registerOffset = isSrv ? srvRegisterOffset : uavRegisterOffset;

            CBVSRVUAVdescriptorSetLayout.addRange(
                descriptorType, denoiserDesc.resourcesBaseRegisterIndex + registerOffset, nrdDescriptorRange.descriptorsNum,
                denoiserDesc.resourcesSpaceIndex
            );
            registerOffset += nrdDescriptorRange.descriptorsNum;
        }
#else
    // Get denoiser desc for currently initialized denoiser implementation.
    const nrd::DenoiserDesc& denoiserDesc = nrd::GetDenoiserDesc(*mpDenoiser);

    // Create samplers descriptor layout and set.
    D3D12DescriptorSetLayout SamplersDescriptorSetLayout;

    for (uint32_t j = 0; j < denoiserDesc.staticSamplerNum; j++)
    {
        SamplersDescriptorSetLayout.addRange(ShaderResourceType::Sampler, denoiserDesc.staticSamplers[j].registerIndex, 1);
    }
    mpSamplersDescriptorSet =
        D3D12DescriptorSet::create(mpDevice, SamplersDescriptorSetLayout, D3D12DescriptorSetBindingUsage::ExplicitBind);

    // Set sampler descriptors right away.
    for (uint32_t j = 0; j < denoiserDesc.staticSamplerNum; j++)
    {
        mpSamplersDescriptorSet->setSampler(0, j, mpSamplers[j].get());
    }

    // Go over NRD passes and creating descriptor sets, root signatures and PSOs for each.
    for (uint32_t i = 0; i < denoiserDesc.pipelineNum; i++)
    {
        const nrd::PipelineDesc& nrdPipelineDesc = denoiserDesc.pipelines[i];

        // Initialize descriptor set.
        D3D12DescriptorSetLayout CBVSRVUAVdescriptorSetLayout;

        // Add constant buffer to descriptor set.
        CBVSRVUAVdescriptorSetLayout.addRange(ShaderResourceType::Cbv, denoiserDesc.constantBufferDesc.registerIndex, 1);

        for (uint32_t j = 0; j < nrdPipelineDesc.descriptorRangeNum; j++)
        {
            const nrd::DescriptorRangeDesc& nrdDescriptorRange = nrdPipelineDesc.descriptorRanges[j];

            ShaderResourceType descriptorType = nrdDescriptorRange.descriptorType == nrd::DescriptorType::TEXTURE
                                                    ? ShaderResourceType::TextureSrv
                                                    : ShaderResourceType::TextureUav;

            CBVSRVUAVdescriptorSetLayout.addRange(descriptorType, nrdDescriptorRange.baseRegisterIndex, nrdDescriptorRange.descriptorNum);
        }
#endif

        mCBVSRVUAVdescriptorSetLayouts.push_back(CBVSRVUAVdescriptorSetLayout);

        // Create root signature for the NRD pass.
        D3D12RootSignature::Desc rootSignatureDesc;
        rootSignatureDesc.addDescriptorSet(SamplersDescriptorSetLayout);
        rootSignatureDesc.addDescriptorSet(CBVSRVUAVdescriptorSetLayout);

        const D3D12RootSignature::Desc& desc = rootSignatureDesc;

        ref<D3D12RootSignature> pRootSig = D3D12RootSignature::create(mpDevice, desc);

        mpRootSignatures.push_back(pRootSig);

        // Create Compute PSO for the NRD pass.
        {
            DefineList defines;
            defines.add("NRD_COMPILER_DXC");
#if FALCOR_HAS_NRD4
            // v4 gates the permutation macros (RADIANCE/SH/OCCLUSION, DIFF/SPEC/BOTH) behind
            // NRD_INTERNAL, which its own build defines. Without it NRD_SIGNAL expands against
            // undefined symbols, so NRD_DIFF and NRD_SPEC both evaluate false and the shaders
            // silently compile with no signal selected.
            defines.add("NRD_INTERNAL");

            // v4 RENAMED the encoding macros. NRD_USE_OCT_NORMAL_ENCODING / NRD_USE_MATERIAL_ID are
            // simply ignored by v4's shaders, which read NRD_NORMAL_ENCODING / NRD_ROUGHNESS_ENCODING
            // from NRDConfig.hlsli instead. Setting them here rather than inheriting that header's
            // defaults keeps the contract with NRDAdapter's packing explicit and in one place.
            // Cross-checked against the linked library in reinit(); see kNrdNormalEncoding.
            defines.add("NRD_NORMAL_ENCODING", std::to_string(kNrdNormalEncoding));
            defines.add("NRD_ROUGHNESS_ENCODING", std::to_string(kNrdRoughnessEncoding));
#else
            defines.add("NRD_USE_OCT_NORMAL_ENCODING", "1");
            defines.add("NRD_USE_MATERIAL_ID", "0");
#endif

#if FALCOR_HAS_NRD4
            // v4 replaces shaderFileName + shaderEntryPointName with a single packed identifier:
            //   "fileName|macro1=value1|macro2=value2..."
            // The macros are NOT optional decoration -- v4 compiles each shader once per
            // permutation of NRD_SIGNAL={DIFF,SPEC,BOTH} x NRD_MODE={RADIANCE,SH,OCCLUSION,DO}
            // (see Shaders.cfg), and NRD_MODE=SH is precisely how spherical-harmonics mode is
            // selected. Dropping them yields a pipeline that compiles and runs but denoises the
            // wrong signal, which no error would reveal.
            std::string identifier(nrdPipelineDesc.shaderIdentifier);
            std::string shaderName = identifier;
            if (size_t firstBar = identifier.find('|'); firstBar != std::string::npos)
            {
                shaderName = identifier.substr(0, firstBar);
                size_t pos = firstBar + 1;
                while (pos <= identifier.size())
                {
                    const size_t nextBar = identifier.find('|', pos);
                    const std::string token = identifier.substr(pos, nextBar == std::string::npos ? std::string::npos : nextBar - pos);
                    if (const size_t eq = token.find('='); eq != std::string::npos)
                        defines.add(token.substr(0, eq), token.substr(eq + 1));
                    else if (!token.empty())
                        defines.add(token);
                    if (nextBar == std::string::npos)
                        break;
                    pos = nextBar + 1;
                }
            }
            // v4's tree is flat and the names already carry ".cs.hlsl"; v3.1 nested under Source/
            // and needed the extension appended.
            std::string shaderFileName = "nrd/Shaders/" + shaderName;
            const char* entryPoint = denoiserDesc.shaderEntryPoint;
#else
            std::string shaderFileName = "nrd/Shaders/Source/" + std::string(nrdPipelineDesc.shaderFileName) + ".hlsl";
            const char* entryPoint = nrdPipelineDesc.shaderEntryPointName;
#endif

            ProgramDesc programDesc;
            programDesc.addShaderLibrary(shaderFileName).csEntry(entryPoint);
            programDesc.setCompilerFlags(SlangCompilerFlags::MatrixLayoutColumnMajor);
            // Disable warning 30056: non-short-circuiting `?:` operator is deprecated, use 'select' instead.
            programDesc.setCompilerArguments({"-Wno-30056"});
            ref<ComputePass> pPass = ComputePass::create(mpDevice, programDesc, defines);

            ref<Program> pProgram = pPass->getProgram();
            ref<const ProgramKernels> pProgramKernels = pProgram->getActiveVersion()->getKernels(mpDevice.get(), pPass->getVars().get());

            ComputeStateObjectDesc csoDesc;
            csoDesc.pProgramKernels = pProgramKernels;
            csoDesc.pD3D12RootSignatureOverride = pRootSig;

            ref<ComputeStateObject> pCSO = mpDevice->createComputeStateObject(csoDesc);

            mpPasses.push_back(pPass);
            mpCachedProgramKernels.push_back(pProgramKernels);
            mpCSOs.push_back(pCSO);
        }
    }
}

void NRDPass::createResources()
{
    // Destroy previously created resources.
    mpSamplers.clear();
    mpPermanentTextures.clear();
    mpTransientTextures.clear();

#if FALCOR_HAS_NRD4
    const nrd::InstanceDesc& denoiserDesc = *nrd::GetInstanceDesc(*mpInstance);
    const uint32_t poolSize = denoiserDesc.permanentPoolSize + denoiserDesc.transientPoolSize;

    // v4 exposes samplers as a plain Sampler[] and dropped both MIRRORED_REPEAT variants, so every
    // sampler is clamped and only the filter varies. Note LINEAR_CLAMP moved from value 2 to 1 --
    // anything that indexed this enum numerically would now bind the wrong sampler.
    for (uint32_t i = 0; i < denoiserDesc.samplersNum; i++)
    {
        const nrd::Sampler nrdSampler = denoiserDesc.samplers[i];
        Sampler::Desc samplerDesc;
        samplerDesc.setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
        if (nrdSampler == nrd::Sampler::NEAREST_CLAMP)
            samplerDesc.setFilterMode(TextureFilteringMode::Point, TextureFilteringMode::Point, TextureFilteringMode::Point);
        else
            samplerDesc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point);

        mpSamplers.push_back(mpDevice->createSampler(samplerDesc));
    }

    // v4's TextureDesc carries only {format, downsampleFactor} -- width/height/mipNum are gone, and
    // the pool is sized from CommonSettings::resourceSize instead. Record the size we built for so
    // executeInternal() can rebuild when the resolution changes (v3.1 could allocate once, because
    // resolution was fixed at creation).
    mPoolResourceSize = mScreenSize;

    for (uint32_t i = 0; i < poolSize; i++)
    {
        const bool isPermanent = (i < denoiserDesc.permanentPoolSize);
        const nrd::TextureDesc& nrdTextureDesc =
            isPermanent ? denoiserDesc.permanentPool[i] : denoiserDesc.transientPool[i - denoiserDesc.permanentPoolSize];

        const uint32_t downsample = std::max(1u, uint32_t(nrdTextureDesc.downsampleFactor));
        const uint32_t width = div_round_up(mScreenSize.x, downsample);
        const uint32_t height = div_round_up(mScreenSize.y, downsample);

        ResourceFormat textureFormat = getFalcorFormat(nrdTextureDesc.format);
        ref<Texture> pTexture = mpDevice->createTexture2D(
            width,
            height,
            textureFormat,
            1u,
            1u, // v4 pool textures are always single-mip; ResourceDesc no longer carries mip info.
            nullptr,
            ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess
        );

        if (isPermanent)
            mpPermanentTextures.push_back(pTexture);
        else
            mpTransientTextures.push_back(pTexture);
    }
#else
    const nrd::DenoiserDesc& denoiserDesc = nrd::GetDenoiserDesc(*mpDenoiser);
    const uint32_t poolSize = denoiserDesc.permanentPoolSize + denoiserDesc.transientPoolSize;

    // Create samplers.
    for (uint32_t i = 0; i < denoiserDesc.staticSamplerNum; i++)
    {
        const nrd::StaticSamplerDesc& nrdStaticsampler = denoiserDesc.staticSamplers[i];
        Sampler::Desc samplerDesc;
        samplerDesc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point);

        if (nrdStaticsampler.sampler == nrd::Sampler::NEAREST_CLAMP || nrdStaticsampler.sampler == nrd::Sampler::LINEAR_CLAMP)
        {
            samplerDesc.setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
        }
        else
        {
            samplerDesc.setAddressingMode(TextureAddressingMode::Mirror, TextureAddressingMode::Mirror, TextureAddressingMode::Mirror);
        }

        if (nrdStaticsampler.sampler == nrd::Sampler::NEAREST_CLAMP || nrdStaticsampler.sampler == nrd::Sampler::NEAREST_MIRRORED_REPEAT)
        {
            samplerDesc.setFilterMode(TextureFilteringMode::Point, TextureFilteringMode::Point, TextureFilteringMode::Point);
        }
        else
        {
            samplerDesc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point);
        }

        mpSamplers.push_back(mpDevice->createSampler(samplerDesc));
    }

    // Texture pool.
    for (uint32_t i = 0; i < poolSize; i++)
    {
        const bool isPermanent = (i < denoiserDesc.permanentPoolSize);

        // Get texture desc.
        const nrd::TextureDesc& nrdTextureDesc =
            isPermanent ? denoiserDesc.permanentPool[i] : denoiserDesc.transientPool[i - denoiserDesc.permanentPoolSize];

        // Create texture.
        ResourceFormat textureFormat = getFalcorFormat(nrdTextureDesc.format);
        ref<Texture> pTexture = mpDevice->createTexture2D(
            nrdTextureDesc.width,
            nrdTextureDesc.height,
            textureFormat,
            1u,
            nrdTextureDesc.mipNum,
            nullptr,
            ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess
        );

        if (isPermanent)
            mpPermanentTextures.push_back(pTexture);
        else
            mpTransientTextures.push_back(pTexture);
    }
#endif
}

#if FALCOR_HAS_NRD4
void NRDPass::resolveSh(
    RenderContext* pRenderContext,
    const RenderData& renderData,
    const ref<Texture>& pSh0,
    const ref<Texture>& pSh1,
    const ref<Texture>& pOut,
    bool sh0IsLinearRgb
)
{
    FALCOR_PROFILE(pRenderContext, "ResolveSh");
    // Names the missing one. An unallocated SH texture presents as a null here and, if passed on,
    // faults inside the dispatch with no indication of which resource was at fault.
    FALCOR_CHECK(
        pSh0 && pSh1 && pOut,
        "NRDPass: SH resolve is missing a texture (sh0={}, sh1={}, out={}). An SH pin declared "
        "Optional is not allocated when nothing consumes it.",
        pSh0 != nullptr, pSh1 != nullptr, pOut != nullptr
    );

    ref<ComputePass> pResolve = (mShResolveMode == ShResolveMode::Cosine) ? mpResolveShPassCosine : mpResolveShPassDc;
    auto var = pResolve->getRootVar()["PerImageCB"];
    var["gResolution"] = mScreenSize;
    var["gSh0IsLinearRgb"] = sh0IsLinearRgb;
    var["gInSh0"] = pSh0;
    var["gInSh1"] = pSh1;
    var["gNormalRoughness"] = renderData.getTexture(kInputNormalRoughnessMaterialID);
    var["gOutRadianceHitDist"] = pOut;
    pResolve->execute(pRenderContext, uint3(mScreenSize.x, mScreenSize.y, 1u));
}
#endif

void NRDPass::executeInternal(RenderContext* pRenderContext, const RenderData& renderData)
{
    FALCOR_ASSERT(mpScene);

    if (mRecreateDenoiser)
    {
        reinit();
    }

    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSpecular)
    {
        // Run classic Falcor compute pass to pack radiance.
        {
            FALCOR_PROFILE(pRenderContext, "PackRadiance");
            auto perImageCB = mpPackRadiancePassRelax->getRootVar()["PerImageCB"];

            perImageCB["gMaxIntensity"] = mMaxIntensity;
            perImageCB["gDiffuseRadianceHitDist"] = renderData.getTexture(kInputDiffuseRadianceHitDist);
            perImageCB["gSpecularRadianceHitDist"] = renderData.getTexture(kInputSpecularRadianceHitDist);
            mpPackRadiancePassRelax->execute(pRenderContext, uint3(mScreenSize.x, mScreenSize.y, 1u));
        }

#if FALCOR_HAS_NRD4
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mRelaxSettings));
#else
        nrd::SetMethodSettings(*mpDenoiser, nrd::Method::RELAX_DIFFUSE_SPECULAR, static_cast<void*>(&mRelaxDiffuseSpecularSettings));
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::RelaxDiffuse)
    {
        // Run classic Falcor compute pass to pack radiance and hit distance.
        {
            FALCOR_PROFILE(pRenderContext, "PackRadianceHitDist");
            auto perImageCB = mpPackRadiancePassRelax->getRootVar()["PerImageCB"];

            perImageCB["gMaxIntensity"] = mMaxIntensity;
            perImageCB["gDiffuseRadianceHitDist"] = renderData.getTexture(kInputDiffuseRadianceHitDist);
            mpPackRadiancePassRelax->execute(pRenderContext, uint3(mScreenSize.x, mScreenSize.y, 1u));
        }

#if FALCOR_HAS_NRD4
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mRelaxSettings));
#else
        nrd::SetMethodSettings(*mpDenoiser, nrd::Method::RELAX_DIFFUSE, static_cast<void*>(&mRelaxDiffuseSettings));
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::ReblurDiffuseSpecular)
    {
        // Run classic Falcor compute pass to pack radiance and hit distance.
        {
            FALCOR_PROFILE(pRenderContext, "PackRadianceHitDist");
            auto perImageCB = mpPackRadiancePassReblur->getRootVar()["PerImageCB"];

            perImageCB["gHitDistParams"].setBlob(mReblurSettings.hitDistanceParameters);
            perImageCB["gMaxIntensity"] = mMaxIntensity;
            perImageCB["gDiffuseRadianceHitDist"] = renderData.getTexture(kInputDiffuseRadianceHitDist);
            perImageCB["gSpecularRadianceHitDist"] = renderData.getTexture(kInputSpecularRadianceHitDist);
            perImageCB["gNormalRoughness"] = renderData.getTexture(kInputNormalRoughnessMaterialID);
            perImageCB["gViewZ"] = renderData.getTexture(kInputViewZ);
            mpPackRadiancePassReblur->execute(pRenderContext, uint3(mScreenSize.x, mScreenSize.y, 1u));
        }

#if FALCOR_HAS_NRD4
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mReblurSettings));
#else
        nrd::SetMethodSettings(*mpDenoiser, nrd::Method::REBLUR_DIFFUSE_SPECULAR, static_cast<void*>(&mReblurSettings));
#endif
    }
#if FALCOR_HAS_NRD4
    else if (mDenoisingMethod == DenoisingMethod::RelaxSpecular || mDenoisingMethod == DenoisingMethod::RelaxDiffuseSh)
    {
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mRelaxSettings));
    }
    else if (mDenoisingMethod == DenoisingMethod::ReblurDiffuse || mDenoisingMethod == DenoisingMethod::ReblurSpecular ||
             mDenoisingMethod == DenoisingMethod::ReblurDiffuseOcclusion || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSh)
    {
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mReblurSettings));
    }
    else if (mDenoisingMethod == DenoisingMethod::SigmaShadow || mDenoisingMethod == DenoisingMethod::SigmaShadowTranslucency)
    {
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mSigmaSettings));
    }
    else if (mDenoisingMethod == DenoisingMethod::Reference)
    {
        nrd::SetDenoiserSettings(*mpInstance, kDenoiserIdentifier, static_cast<void*>(&mReferenceSettings));
    }
#endif
    else if (mDenoisingMethod == DenoisingMethod::SpecularReflectionMv)
    {
#if FALCOR_HAS_NRD4
        FALCOR_THROW("NRDPass: SpecularReflectionMv was removed in NRD v4. Build with FALCOR_USE_NRD4=OFF.");
#else
        nrd::SpecularReflectionMvSettings specularReflectionMvSettings;
        nrd::SetMethodSettings(*mpDenoiser, nrd::Method::SPECULAR_REFLECTION_MV, static_cast<void*>(&specularReflectionMvSettings));
#endif
    }
    else if (mDenoisingMethod == DenoisingMethod::SpecularDeltaMv)
    {
#if FALCOR_HAS_NRD4
        FALCOR_THROW("NRDPass: SpecularDeltaMv was removed in NRD v4. Build with FALCOR_USE_NRD4=OFF.");
#else
        nrd::SpecularDeltaMvSettings specularDeltaMvSettings;
        nrd::SetMethodSettings(*mpDenoiser, nrd::Method::SPECULAR_DELTA_MV, static_cast<void*>(&specularDeltaMvSettings));
#endif
    }
    else
    {
        FALCOR_UNREACHABLE();
        return;
    }

    // Initialize common settings.
    float4x4 viewMatrix = mpScene->getCamera()->getViewMatrix();
    float4x4 projMatrix = mpScene->getCamera()->getData().projMatNoJitter;
    if (mFrameIndex == 0)
    {
        mPrevViewMatrix = viewMatrix;
        mPrevProjMatrix = projMatrix;
    }

    copyMatrix(mCommonSettings.viewToClipMatrix, projMatrix);
    copyMatrix(mCommonSettings.viewToClipMatrixPrev, mPrevProjMatrix);
    copyMatrix(mCommonSettings.worldToViewMatrix, viewMatrix);
    copyMatrix(mCommonSettings.worldToViewMatrixPrev, mPrevViewMatrix);
    // NRD's convention for the jitter is: [-0.5; 0.5] sampleUv = pixelUv + cameraJitter
    mCommonSettings.cameraJitter[0] = -mpScene->getCamera()->getJitterX();
    mCommonSettings.cameraJitter[1] = mpScene->getCamera()->getJitterY();
    mCommonSettings.denoisingRange = kNRDDepthRange;
    mCommonSettings.disocclusionThreshold = mDisocclusionThreshold * 0.01f;
    mCommonSettings.frameIndex = mFrameIndex;
    mCommonSettings.isMotionVectorInWorldSpace = mWorldSpaceMotion;

#if FALCOR_HAS_NRD4
    // Resolution moved out of denoiser creation and into CommonSettings. All four of these default
    // to {0,0}, and nothing else tells NRD how big anything is, so omitting them fails outright.
    // resourceSize is the allocated texture size; rectSize is the rendered viewport (they differ
    // only under dynamic resolution, which we do not use).
    mCommonSettings.resourceSize[0] = uint16_t(mScreenSize.x);
    mCommonSettings.resourceSize[1] = uint16_t(mScreenSize.y);
    mCommonSettings.rectSize[0] = uint16_t(mScreenSize.x);
    mCommonSettings.rectSize[1] = uint16_t(mScreenSize.y);

    // The *Prev values have no v3.1 equivalent and default to zero, which degrades reprojection
    // silently rather than erroring. On the first frame seed them from the current values.
    const bool firstFrame = (mFrameIndex == 0) || any(mPrevResourceSize == 0u);
    mCommonSettings.resourceSizePrev[0] = uint16_t(firstFrame ? mScreenSize.x : mPrevResourceSize.x);
    mCommonSettings.resourceSizePrev[1] = uint16_t(firstFrame ? mScreenSize.y : mPrevResourceSize.y);
    mCommonSettings.rectSizePrev[0] = uint16_t(firstFrame ? mScreenSize.x : mPrevRectSize.x);
    mCommonSettings.rectSizePrev[1] = uint16_t(firstFrame ? mScreenSize.y : mPrevRectSize.y);

    // Likewise new in v4, and likewise zero-defaulted.
    mCommonSettings.cameraJitterPrev[0] = firstFrame ? mCommonSettings.cameraJitter[0] : mPrevCameraJitter.x;
    mCommonSettings.cameraJitterPrev[1] = firstFrame ? mCommonSettings.cameraJitter[1] : mPrevCameraJitter.y;

    // motionVectorScale grew from float[2] to float[3] and the new element defaults to 0. We feed
    // 2D screen-space motion vectors already in normalized UV, so the scale is identity and .z is
    // deliberately 0. (With world-space motion, leaving .z at 0 would silently zero the Z of the
    // motion -- wrong reprojection, no error.)
    mCommonSettings.motionVectorScale[0] = 1.f;
    mCommonSettings.motionVectorScale[1] = 1.f;
    mCommonSettings.motionVectorScale[2] = mWorldSpaceMotion ? 1.f : 0.f;

    mCommonSettings.disocclusionThresholdAlternate = mDisocclusionThresholdAlternate * 0.01f;
    mCommonSettings.strandThickness = mStrandThickness;
    mCommonSettings.strandMaterialID = mStrandMaterialID;
    mCommonSettings.cameraAttachedReflectionMaterialID = mCameraAttachedReflectionMaterialID;
    mCommonSettings.splitScreen = mSplitScreen;
    mCommonSettings.enableValidation = mEnableValidation && renderData.getTexture(kOutputValidation) != nullptr;

    // Announce optional inputs ONLY when the graph actually bound them. NRD does not check: telling it
    // a confidence texture exists when nothing is connected makes it read an unbound resource, which
    // reads as "confidence 0 everywhere" -- it would quietly relax every weight rather than error.
    mCommonSettings.isHistoryConfidenceAvailable = renderData.getTexture(kInputDiffuseConfidence) != nullptr &&
                                                   renderData.getTexture(kInputSpecularConfidence) != nullptr;
    mCommonSettings.isDisocclusionThresholdMixAvailable = renderData.getTexture(kInputDisocclusionThresholdMix) != nullptr;


    mPrevResourceSize = mScreenSize;
    mPrevRectSize = mScreenSize;
    mPrevCameraJitter = float2(mCommonSettings.cameraJitter[0], mCommonSettings.cameraJitter[1]);
#endif

    mPrevViewMatrix = viewMatrix;
    mPrevProjMatrix = projMatrix;
    mFrameIndex++;

    // Run NRD dispatches.
    const nrd::DispatchDesc* dispatchDescs = nullptr;
    uint32_t dispatchDescNum = 0;
#if FALCOR_HAS_NRD4
    // v4 splits this in two: settings are pushed first and validated there, then dispatches are
    // requested for a chosen subset of denoisers. SetCommonSettings returns a Result worth checking
    // -- it is where a missing resourceSize/rectSize surfaces.
    nrd::Result settingsResult = nrd::SetCommonSettings(*mpInstance, mCommonSettings);
    FALCOR_CHECK(settingsResult == nrd::Result::SUCCESS, "NRDPass: SetCommonSettings failed (result {}).", uint32_t(settingsResult));

    const nrd::Identifier identifiers[] = {kDenoiserIdentifier};
    nrd::Result result = nrd::GetComputeDispatches(*mpInstance, identifiers, 1, dispatchDescs, dispatchDescNum);
#else
    nrd::Result result = nrd::GetComputeDispatches(*mpDenoiser, mCommonSettings, dispatchDescs, dispatchDescNum);
#endif
    FALCOR_ASSERT(result == nrd::Result::SUCCESS);

    for (uint32_t i = 0; i < dispatchDescNum; i++)
    {
        const nrd::DispatchDesc& dispatchDesc = dispatchDescs[i];
        FALCOR_PROFILE(pRenderContext, dispatchDesc.name);
        dispatch(pRenderContext, renderData, dispatchDesc);
    }

#if FALCOR_HAS_NRD4
    // SH mode emits a coefficient pair; turn it back into radiance before anything downstream sees
    // it. Symmetric with PackRadiance running before the dispatches.
    if (mDenoisingMethod == DenoisingMethod::RelaxDiffuseSh || mDenoisingMethod == DenoisingMethod::ReblurDiffuseSh)
    {
        resolveSh(
            pRenderContext,
            renderData,
            renderData.getTexture(kOutputDiffuseSh0),
            renderData.getTexture(kOutputDiffuseSh1),
            renderData.getTexture(kOutputFilteredDiffuseRadianceHitDist),
            false // NRD's output is YCoCg
        );
    }
#endif

    // Submit the existing command list and start a new one.
    pRenderContext->submit();
}

void NRDPass::dispatch(RenderContext* pRenderContext, const RenderData& renderData, const nrd::DispatchDesc& dispatchDesc)
{
#if FALCOR_HAS_NRD4
    const nrd::InstanceDesc& denoiserDesc = *nrd::GetInstanceDesc(*mpInstance);
#else
    const nrd::DenoiserDesc& denoiserDesc = nrd::GetDenoiserDesc(*mpDenoiser);
#endif
    const nrd::PipelineDesc& pipelineDesc = denoiserDesc.pipelines[dispatchDesc.pipelineIndex];

    // Set root signature.
    mpRootSignatures[dispatchDesc.pipelineIndex]->bindForCompute(pRenderContext);

    // Upload constants.
    auto cbAllocation = mpDevice->getUploadHeap()->allocate(dispatchDesc.constantBufferDataSize, ResourceBindFlags::Constant);
    std::memcpy(cbAllocation.pData, dispatchDesc.constantBufferData, dispatchDesc.constantBufferDataSize);

    // Create descriptor set for the NRD pass.
    ref<D3D12DescriptorSet> CBVSRVUAVDescriptorSet = D3D12DescriptorSet::create(
        mpDevice, mCBVSRVUAVdescriptorSetLayouts[dispatchDesc.pipelineIndex], D3D12DescriptorSetBindingUsage::ExplicitBind
    );

    // Set CBV.
    mpCBV = D3D12ConstantBufferView::create(mpDevice, cbAllocation.getGpuAddress(), cbAllocation.size);
#if FALCOR_HAS_NRD4
    CBVSRVUAVDescriptorSet->setCbv(0 /* NB: range #0 is CBV range */, denoiserDesc.constantBufferRegisterIndex, mpCBV.get());
#else
    CBVSRVUAVDescriptorSet->setCbv(0 /* NB: range #0 is CBV range */, denoiserDesc.constantBufferDesc.registerIndex, mpCBV.get());
#endif

    uint32_t resourceIndex = 0;
#if FALCOR_HAS_NRD4
    // v4: registers run consecutively from resourcesBaseRegisterIndex, but SRVs and UAVs are
    // separate register classes that each restart at the base. Must match createPipelines() exactly
    // -- these registers are what the descriptors are looked up by.
    uint32_t srvRegisterOffset = 0;
    uint32_t uavRegisterOffset = 0;
    for (uint32_t descriptorRangeIndex = 0; descriptorRangeIndex < pipelineDesc.resourceRangesNum; descriptorRangeIndex++)
#else
    for (uint32_t descriptorRangeIndex = 0; descriptorRangeIndex < pipelineDesc.descriptorRangeNum; descriptorRangeIndex++)
#endif
    {
#if FALCOR_HAS_NRD4
        const nrd::ResourceRangeDesc& nrdDescriptorRange = pipelineDesc.resourceRanges[descriptorRangeIndex];
        const uint32_t rangeDescriptorNum = nrdDescriptorRange.descriptorsNum;
        const bool rangeIsSrv = nrdDescriptorRange.descriptorType == nrd::DescriptorType::TEXTURE;
        uint32_t& registerOffset = rangeIsSrv ? srvRegisterOffset : uavRegisterOffset;
        const uint32_t rangeBaseRegister = denoiserDesc.resourcesBaseRegisterIndex + registerOffset;
#else
        const nrd::DescriptorRangeDesc& nrdDescriptorRange = pipelineDesc.descriptorRanges[descriptorRangeIndex];
        const uint32_t rangeDescriptorNum = nrdDescriptorRange.descriptorNum;
        const uint32_t rangeBaseRegister = nrdDescriptorRange.baseRegisterIndex;
#endif

        for (uint32_t descriptorOffset = 0; descriptorOffset < rangeDescriptorNum; descriptorOffset++)
        {
#if FALCOR_HAS_NRD4
            FALCOR_ASSERT(resourceIndex < dispatchDesc.resourcesNum);
            const nrd::ResourceDesc& resource = dispatchDesc.resources[resourceIndex];
            const nrd::DescriptorType resourceDescriptorType = resource.descriptorType;
            // v4 removed mipOffset/mipNum -- every descriptor is a whole, single-mip texture.
            const uint16_t resourceMipOffset = 0;
            const uint16_t resourceMipNum = 1;
#else
            FALCOR_ASSERT(resourceIndex < dispatchDesc.resourceNum);
            const nrd::Resource& resource = dispatchDesc.resources[resourceIndex];
            const nrd::DescriptorType resourceDescriptorType = resource.stateNeeded;
            const uint16_t resourceMipOffset = resource.mipOffset;
            const uint16_t resourceMipNum = resource.mipNum;
#endif

            FALCOR_ASSERT(resourceDescriptorType == nrdDescriptorRange.descriptorType);

            ref<Texture> texture;

            switch (resource.type)
            {
            case nrd::ResourceType::IN_MV:
                texture = renderData.getTexture(kInputMotionVectors);
                break;
            case nrd::ResourceType::IN_NORMAL_ROUGHNESS:
                texture = renderData.getTexture(kInputNormalRoughnessMaterialID);
                break;
            case nrd::ResourceType::IN_VIEWZ:
                texture = renderData.getTexture(kInputViewZ);
                break;
            case nrd::ResourceType::IN_DIFF_RADIANCE_HITDIST:
                texture = renderData.getTexture(kInputDiffuseRadianceHitDist);
                break;
            case nrd::ResourceType::IN_SPEC_RADIANCE_HITDIST:
                texture = renderData.getTexture(kInputSpecularRadianceHitDist);
                break;
            case nrd::ResourceType::IN_SPEC_HITDIST:
                texture = renderData.getTexture(kInputSpecularHitDist);
                break;
#if !FALCOR_HAS_NRD4
            // Removed in NRD v4 together with the SpecularReflectionMv / SpecularDeltaMv denoisers.
            case nrd::ResourceType::IN_DELTA_PRIMARY_POS:
                texture = renderData.getTexture(kInputDeltaPrimaryPosW);
                break;
            case nrd::ResourceType::IN_DELTA_SECONDARY_POS:
                texture = renderData.getTexture(kInputDeltaSecondaryPosW);
                break;
#endif
            case nrd::ResourceType::OUT_DIFF_RADIANCE_HITDIST:
                texture = renderData.getTexture(kOutputFilteredDiffuseRadianceHitDist);
                break;
            case nrd::ResourceType::OUT_SPEC_RADIANCE_HITDIST:
                texture = renderData.getTexture(kOutputFilteredSpecularRadianceHitDist);
                break;
#if FALCOR_HAS_NRD4
            case nrd::ResourceType::IN_DIFF_CONFIDENCE:
                texture = renderData.getTexture(kInputDiffuseConfidence);
                break;
            case nrd::ResourceType::IN_SPEC_CONFIDENCE:
                texture = renderData.getTexture(kInputSpecularConfidence);
                break;
            case nrd::ResourceType::IN_DISOCCLUSION_THRESHOLD_MIX:
                texture = renderData.getTexture(kInputDisocclusionThresholdMix);
                break;
            case nrd::ResourceType::IN_DIFF_HITDIST:
                texture = renderData.getTexture(kInputDiffuseHitDist);
                break;
            case nrd::ResourceType::IN_PENUMBRA:
                texture = renderData.getTexture(kInputPenumbra);
                break;
            case nrd::ResourceType::IN_TRANSLUCENCY:
                texture = renderData.getTexture(kInputTranslucency);
                break;
            case nrd::ResourceType::IN_SIGNAL:
                texture = renderData.getTexture(kInputSignal);
                break;
            case nrd::ResourceType::IN_DIFF_SH0:
                texture = renderData.getTexture(kInputDiffuseSh0);
                break;
            case nrd::ResourceType::IN_DIFF_SH1:
                texture = renderData.getTexture(kInputDiffuseSh1);
                break;
            case nrd::ResourceType::OUT_DIFF_SH0:
                texture = renderData.getTexture(kOutputDiffuseSh0);
                break;
            case nrd::ResourceType::OUT_DIFF_SH1:
                texture = renderData.getTexture(kOutputDiffuseSh1);
                break;
            case nrd::ResourceType::OUT_DIFF_HITDIST:
                texture = renderData.getTexture(kOutputFilteredDiffuseHitDist);
                break;
            case nrd::ResourceType::OUT_SHADOW_TRANSLUCENCY:
                texture = renderData.getTexture(kOutputShadowTranslucency);
                break;
            case nrd::ResourceType::OUT_SIGNAL:
                texture = renderData.getTexture(kOutputSignal);
                break;
            case nrd::ResourceType::OUT_VALIDATION:
                texture = renderData.getTexture(kOutputValidation);
                break;
#endif
#if !FALCOR_HAS_NRD4
            // Removed in NRD v4 together with the SpecularReflectionMv / SpecularDeltaMv denoisers.
            case nrd::ResourceType::OUT_REFLECTION_MV:
                texture = renderData.getTexture(kOutputReflectionMotionVectors);
                break;
            case nrd::ResourceType::OUT_DELTA_MV:
                texture = renderData.getTexture(kOutputDeltaMotionVectors);
                break;
#endif
            case nrd::ResourceType::TRANSIENT_POOL:
                texture = mpTransientTextures[resource.indexInPool];
                break;
            case nrd::ResourceType::PERMANENT_POOL:
                texture = mpPermanentTextures[resource.indexInPool];
                break;
            default:
                FALCOR_ASSERT(!"Unavailable resource type");
                break;
            }

            FALCOR_ASSERT(texture);

            // Set up resource barriers.
            Resource::State newState =
                resourceDescriptorType == nrd::DescriptorType::TEXTURE ? Resource::State::ShaderResource : Resource::State::UnorderedAccess;
            for (uint16_t mip = 0; mip < resourceMipNum; mip++)
            {
                const ResourceViewInfo viewInfo = ResourceViewInfo(resourceMipOffset + mip, 1, 0, 1);
                pRenderContext->resourceBarrier(texture.get(), newState, &viewInfo);
            }

            // Set the SRV and UAV descriptors.
            if (nrdDescriptorRange.descriptorType == nrd::DescriptorType::TEXTURE)
            {
                ref<ShaderResourceView> pSRV = texture->getSRV(resourceMipOffset, resourceMipNum, 0, 1);
                CBVSRVUAVDescriptorSet->setSrv(
                    descriptorRangeIndex + 1 /* NB: range #0 is CBV range */, rangeBaseRegister + descriptorOffset, pSRV.get()
                );
            }
            else
            {
                ref<UnorderedAccessView> pUAV = texture->getUAV(resourceMipOffset, 0, 1);
                CBVSRVUAVDescriptorSet->setUav(
                    descriptorRangeIndex + 1 /* NB: range #0 is CBV range */, rangeBaseRegister + descriptorOffset, pUAV.get()
                );
            }

            resourceIndex++;
        }
#if FALCOR_HAS_NRD4
        registerOffset += rangeDescriptorNum;
#endif
    }

#if FALCOR_HAS_NRD4
    FALCOR_ASSERT(resourceIndex == dispatchDesc.resourcesNum);
#else
    FALCOR_ASSERT(resourceIndex == dispatchDesc.resourceNum);
#endif

    // Set descriptor sets.
    mpSamplersDescriptorSet->bindForCompute(pRenderContext, mpRootSignatures[dispatchDesc.pipelineIndex].get(), 0);
    CBVSRVUAVDescriptorSet->bindForCompute(pRenderContext, mpRootSignatures[dispatchDesc.pipelineIndex].get(), 1);

    // Set pipeline state.
    ref<ComputePass> pPass = mpPasses[dispatchDesc.pipelineIndex];
    ref<Program> pProgram = pPass->getProgram();
    ref<const ProgramKernels> pProgramKernels = pProgram->getActiveVersion()->getKernels(mpDevice.get(), pPass->getVars().get());

    // Check if anything changed.
    bool newProgram = (pProgramKernels.get() != mpCachedProgramKernels[dispatchDesc.pipelineIndex].get());
    if (newProgram)
    {
        mpCachedProgramKernels[dispatchDesc.pipelineIndex] = pProgramKernels;

        ComputeStateObjectDesc desc;
        desc.pProgramKernels = pProgramKernels;
        desc.pD3D12RootSignatureOverride = mpRootSignatures[dispatchDesc.pipelineIndex];

        ref<ComputeStateObject> pCSO = mpDevice->createComputeStateObject(desc);
        mpCSOs[dispatchDesc.pipelineIndex] = pCSO;
    }
    ID3D12GraphicsCommandList* pCommandList =
        pRenderContext->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
    ID3D12PipelineState* pPipelineState = mpCSOs[dispatchDesc.pipelineIndex]->getNativeHandle().as<ID3D12PipelineState*>();

    pCommandList->SetPipelineState(pPipelineState);

    // Dispatch.
    pCommandList->Dispatch(dispatchDesc.gridWidth, dispatchDesc.gridHeight, 1);

    mpDevice->getUploadHeap()->release(cbAllocation);
}

extern "C" FALCOR_API_EXPORT void registerPlugin(PluginRegistry& registry)
{
    registry.registerClass<RenderPass, NRDPass>();
}
