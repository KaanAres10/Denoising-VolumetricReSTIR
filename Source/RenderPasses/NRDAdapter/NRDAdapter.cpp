/***************************************************************************
 # Builds NRD RELAX guide buffers from this renderer's volumetric output.
 **************************************************************************/
#include "NRDAdapter.h"

namespace
{
const char kShaderFile[] = "RenderPasses/NRDAdapter/NRDAdapter.cs.slang";

const char kColorInput[] = "color";
const char kScatterDistanceInput[] = "scatterDistance";
const char kGuideNormalInput[] = "guideNormalW";
const char kSpecRoughInput[] = "specRough";
const char kDiffuseAlbedoInput[] = "diffuseAlbedo";
const char kScatterDensityInput[] = "scatterDensity";
const char kMediumAlphaInput[] = "mediumAlpha";
const char kTransmittanceInput[] = "transmittance";

// Names match NRDPass's input pins so the graph wiring reads directly.
const char kDiffuseRadianceHitDistOutput[] = "diffuseRadianceHitDist";
const char kNormalRoughnessOutput[] = "normWRoughnessMaterialID";
const char kDemodDivisorOutput[] = "demodDivisor";
const char kHistoryConfidenceOutput[] = "historyConfidence";

const char kMinReflectance[] = "minReflectance";
const char kMissHitDistance[] = "missHitDistance";
const char kDemodulateVolume[] = "demodulateVolume";
const char kDemodulateTransmittance[] = "demodulateTransmittance";
const char kMinTransmittance[] = "minTransmittance";
const char kNormalizeBySelection[] = "normalizeBySelection";
const char kSelectionBlur[] = "selectionBlur";
const char kSelectionFloor[] = "selectionFloor";
const char kVolumeStructureBlur[] = "volumeStructureBlur";
const char kVolumeStructureFloor[] = "volumeStructureFloor";
#if FALCOR_HAS_NRD4
const char kShMode[] = "shMode";
const char kShYCoCg[] = "shYCoCg";
// Direction the reservoir's light arrives from, .w = 1 when trustworthy (VolumetricReSTIR.lightDir).
const char kLightDirInput[] = "lightDir";
const char kDiffuseSh0Output[] = "diffuseSh0";
const char kDiffuseSh1Output[] = "diffuseSh1";
#endif
} // namespace

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, NRDAdapter>();
}

NRDAdapter::NRDAdapter(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    for (const auto& [key, value] : props)
    {
        if (key == kMinReflectance)
            mMinReflectance = value;
        else if (key == kMissHitDistance)
            mMissHitDistance = value;
        else if (key == "useScatterDistance")
            mUseScatterDistance = value;
        else if (key == "useNormalGuide")
            mUseNormalGuide = value;
        else if (key == kDemodulateVolume)
            mDemodulateVolume = value;
        else if (key == kDemodulateTransmittance)
            mDemodulateTransmittance = value;
        else if (key == kMinTransmittance)
            mMinTransmittance = value;
        else if (key == kNormalizeBySelection)
            mNormalizeBySelection = value;
        else if (key == kSelectionBlur)
            mSelectionBlur = value;
        else if (key == kSelectionFloor)
            mSelectionFloor = value;
        else if (key == kVolumeStructureBlur)
            mVolumeStructureBlur = value;
        else if (key == kVolumeStructureFloor)
            mVolumeStructureFloor = value;
#if FALCOR_HAS_NRD4
        else if (key == kShMode)
            mShMode = value;
        else if (key == kShYCoCg)
            mShYCoCg = value;
#endif
        else if (key == "outputSize")
            mOutputSizeSelection = value;
        else if (key == "fixedOutputSize")
            mFixedOutputSize = value;
        else if (key == "upscale")
            mUpscaling = value;
        else if (key == "upscaleRatio")
            mUpscaleRatio = value;
        else
            logWarning("Unknown property '{}' in NRDAdapter properties.", key);
    }

    // Always defined, never left to the preprocessor's undefined-is-0 rule, so that a missing
    // FALCOR_HAS_NRD4 shows up as a compile error here rather than as a silently wrong guide layout.
    DefineList defines;
#if FALCOR_HAS_NRD4
    defines.add("NRD_V4", "1");
#else
    defines.add("NRD_V4", "0");
#endif
    defines.add("SH_MODE", "0");
    mpPass = ComputePass::create(mpDevice, kShaderFile, "main", defines);
#if FALCOR_HAS_NRD4
    // Compiled up front rather than on first use so an SH shader error surfaces at graph creation,
    // next to the rest of the setup, instead of mid-benchmark.
    defines.add("SH_MODE", "1");
    mpShPass = ComputePass::create(mpDevice, kShaderFile, "main", defines);
#endif
}

Properties NRDAdapter::getProperties() const
{
    Properties props;
    props[kMinReflectance] = mMinReflectance;
    props[kMissHitDistance] = mMissHitDistance;
    props["useScatterDistance"] = mUseScatterDistance;
    props["useNormalGuide"] = mUseNormalGuide;
    props[kDemodulateVolume] = mDemodulateVolume;
    props[kDemodulateTransmittance] = mDemodulateTransmittance;
    props[kMinTransmittance] = mMinTransmittance;
    props[kNormalizeBySelection] = mNormalizeBySelection;
    props[kSelectionBlur] = mSelectionBlur;
    props[kSelectionFloor] = mSelectionFloor;
    props[kVolumeStructureBlur] = mVolumeStructureBlur;
    props[kVolumeStructureFloor] = mVolumeStructureFloor;
#if FALCOR_HAS_NRD4
    props[kShMode] = mShMode;
#endif
    props["outputSize"] = mOutputSizeSelection;
    if (mOutputSizeSelection == RenderPassHelpers::IOSize::Fixed)
        props["fixedOutputSize"] = mFixedOutputSize;
    props["upscale"] = mUpscaling;
    if (mUpscaling)
        props["upscaleRatio"] = mUpscaleRatio;
    return props;
}

RenderPassReflection NRDAdapter::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kColorInput, "Radiance from VolumetricReSTIR (material included)");
    r.addInput(kScatterDistanceInput, "Expected scatter distance along the primary ray, -1 = no medium");
    r.addInput(kGuideNormalInput, "World-space guide normal (GBuffer guideNormalW)");
    r.addInput(kSpecRoughInput, "Specular reflectance and roughness (GBuffer specRough)");
    r.addInput(kDiffuseAlbedoInput, "Demodulation divisor (DLSSDGuides diffuseAlbedo)");
    // Optional: unwired, the pass behaves exactly as before.
    r.addInput(kScatterDensityInput, "Medium density at the scatter point (volumetric demodulation)")
        .flags(RenderPassReflection::Field::Flags::Optional);
    r.addInput(kMediumAlphaInput, "Medium coverage, the blend weight for volumetric demodulation")
        .flags(RenderPassReflection::Field::Flags::Optional);
    r.addInput(kTransmittanceInput, "Primary-ray transmittance (surface-half demodulation divisor)")
        .flags(RenderPassReflection::Field::Flags::Optional);
#if FALCOR_HAS_NRD4
    // Required in SH mode, and NOT optional: SH1 carries "direction * luminance", so an unbound
    // lightDir would pack an all-zero SH1 -- a perfectly valid-looking "no directional information"
    // input that NRD would denoise without complaint. Declaring it mandatory makes the graph fail to
    // compile instead.
    if (mShMode)
        r.addInput(kLightDirInput, "Dominant light direction at the first scatter vertex (w=1 valid)");
#endif

    // Adopt the graph-wide render scale, as DLSSDGuides and GBufferBase do. Guides allocated at the
    // swapchain size while the colour is at render size misregister by the upscale factor, which
    // shows as edge fringing rather than an error.
    if (getRenderScale().generation != mRenderScaleGen)
    {
        mRenderScaleGen = getRenderScale().generation;
        mUpscaling = getRenderScale().enabled;
        mUpscaleRatio = getRenderScale().ratio;
    }

    uint2 sz;
    if (mUpscaling)
    {
        const float ratio = std::clamp(mUpscaleRatio, 0.25f, 1.f);
        sz = uint2(uint32_t(compileData.defaultTexDims.x * ratio), uint32_t(compileData.defaultTexDims.y * ratio));
        sz = uint2(std::max(sz.x / 2 * 2, 32u), std::max(sz.y / 2 * 2, 32u));
    }
    else
    {
        sz = RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mFixedOutputSize, compileData.defaultTexDims);
    }

#if FALCOR_HAS_NRD4
    if (mShMode)
    {
        // SH0 = {radiance.rgb, hitDist}, SH1 = {direction * luminance(radiance), 0}. RGBA16Float
        // matches what NRDPass reflects for IN_DIFF_SH0/SH1 -- the pair must agree or the graph
        // silently reformats between them.
        r.addOutput(kDiffuseSh0Output, "Diffuse SH0 (radiance, hitDist)")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y)
            .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
        r.addOutput(kDiffuseSh1Output, "Diffuse SH1 (direction * luminance, 0)")
            .format(ResourceFormat::RGBA16Float)
            .texture2D(sz.x, sz.y)
            .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    }
    else
#endif
    // RGBA32Float rather than the RGBA16Float NRD outputs: this carries a world-space hit distance
    // in .a alongside undemodulated-range radiance, and half precision would quantise both.
    r.addOutput(kDiffuseRadianceHitDistOutput, "Demodulated diffuse radiance and hit distance")
        .format(ResourceFormat::RGBA32Float)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    // RGB10A2Unorm is required, not preferred. Under v3.1 NRD decodes it as oct normal + roughness;
    // under v4 as normal and roughness co-packed into the 30-bit field with materialID in A2. Either
    // way the format is dictated by the decoder -- see encodeNormalRoughness in the shader.
    // RGBA32Float to match the radiance it divides: the round trip is only exact if the multiplier
    // downstream is bit-identical to the divisor used here.
    r.addOutput(kDemodDivisorOutput, "Exactly what the radiance was divided by")
        .format(ResourceFormat::RGBA32Float)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    // NRD wants "R8+" and reads a single channel. RGBA16Float keeps the ramp smooth -- at 1/255 the
    // handover between demodulation and history rejection would be a visible staircase.
    r.addOutput(kHistoryConfidenceOutput, "NRD history confidence for the surface half")
        .format(ResourceFormat::RGBA16Float)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    r.addOutput(kNormalRoughnessOutput, "Oct-encoded normal, linear roughness, material ID")
        .format(ResourceFormat::RGB10A2Unorm)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    return r;
}

void NRDAdapter::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
#if FALCOR_HAS_NRD4
    auto pOut = mShMode ? renderData.getTexture(kDiffuseSh0Output) : renderData.getTexture(kDiffuseRadianceHitDistOutput);
#else
    auto pOut = renderData.getTexture(kDiffuseRadianceHitDistOutput);
#endif
    FALCOR_ASSERT(pOut);
    const uint2 resolution = {pOut->getWidth(), pOut->getHeight()};

    // Same guard as DLSSDPass: every input must be pixel-aligned with the output, because a
    // mismatched guide is resampled as though it matched rather than rejected.
    {
        const std::pair<const char*, const Texture*> inputs[] = {
            {kColorInput, renderData.getTexture(kColorInput).get()},
            {kScatterDistanceInput, renderData.getTexture(kScatterDistanceInput).get()},
            {kGuideNormalInput, renderData.getTexture(kGuideNormalInput).get()},
            {kSpecRoughInput, renderData.getTexture(kSpecRoughInput).get()},
            {kDiffuseAlbedoInput, renderData.getTexture(kDiffuseAlbedoInput).get()},
        };
        for (const auto& [name, pTex] : inputs)
        {
            if (pTex == nullptr)
                continue;
            const uint2 sz = {pTex->getWidth(), pTex->getHeight()};
            if (any(sz != resolution) && any(resolution != mWarnedMismatchSize))
            {
                logWarning(
                    "NRDAdapter: input '{}' is {}x{} but the output is {}x{}. NRD assumes all guides "
                    "share the render resolution; a mismatch misregisters rather than failing.",
                    name, sz.x, sz.y, resolution.x, resolution.y
                );
                mWarnedMismatchSize = resolution;
            }
        }
    }

    // SH mode is a compile-time define, not a uniform: the two modes declare DIFFERENT outputs, and
    // Slang requires every declared resource to be bound. A single variant would force dummy
    // bindings for whichever set is unused -- and a texture bound "just to satisfy the binder" is
    // indistinguishable from one that is genuinely in use when reading the code later.
    ref<ComputePass>& pPass = getPass();
    auto var = pPass->getRootVar();

    // Resolved before the constant buffer, because gDemodulateVolume depends on it. Both halves are
    // required: the blur is coverage-weighted, so without mediumAlpha the divisor would dip toward
    // zero at the plume's silhouette.
    const auto pScatterDensity = renderData.getTexture(kScatterDensityInput);
    const auto pMediumAlpha = renderData.getTexture(kMediumAlphaInput);
    const auto pDivisor = renderData.getTexture(kDemodDivisorOutput);
    const bool demod = mDemodulateVolume && pScatterDensity != nullptr && pMediumAlpha != nullptr;
    if (mDemodulateVolume && !demod)
    {
        logWarning("NRDAdapter: '{}' is on but '{}'/'{}' are not connected; volumetric demodulation is disabled.",
                   kDemodulateVolume, kScatterDensityInput, kMediumAlphaInput);
    }
    var["CB"]["gResolution"] = resolution;
    var["CB"]["gMinReflectance"] = mMinReflectance;
    var["CB"]["gMissHitDistance"] = mMissHitDistance;
    var["CB"]["gUseScatterDistance"] = mUseScatterDistance;
    var["CB"]["gUseNormalGuide"] = mUseNormalGuide;
    var["CB"]["gShYCoCg"] = mShYCoCg;
    var["CB"]["gNormalizeBySelection"] = mNormalizeBySelection;
    var["CB"]["gSelectionBlur"] = mSelectionBlur;
    var["CB"]["gSelectionFloor"] = mSelectionFloor;
    var["CB"]["gDemodulateVolume"] = demod;
    var["CB"]["gWriteDemodDivisor"] = pDivisor != nullptr;
    // Gated on its OWN input, individually -- the coupled gate that silently zeroed the volumetric
    // guides is the mistake this project has already paid for once.
    const auto pTransmittance = renderData.getTexture(kTransmittanceInput);
    const bool demodTr = mDemodulateTransmittance && pTransmittance != nullptr;
    if (mDemodulateTransmittance && !demodTr)
    {
        logWarning("NRDAdapter: '{}' is on but '{}' is not connected; transmittance demodulation is disabled.",
                   kDemodulateTransmittance, kTransmittanceInput);
    }
    const auto pConfidence = renderData.getTexture(kHistoryConfidenceOutput);
    var["CB"]["gWriteHistoryConfidence"] = pConfidence != nullptr;
    var["gOutHistoryConfidence"] = pConfidence ? pConfidence : renderData.getTexture(kDiffuseRadianceHitDistOutput);
    var["CB"]["gDemodulateTransmittance"] = demodTr;
    var["CB"]["gMinTransmittance"] = mMinTransmittance;
    // Any bound texture will do when the feature is off; the shader never reads it.
    var["gTransmittance"] = pTransmittance ? pTransmittance : renderData.getTexture(kDiffuseAlbedoInput);
    var["CB"]["gVolumeStructureBlur"] = mVolumeStructureBlur;
    var["CB"]["gVolumeStructureFloor"] = mVolumeStructureFloor;

    var["gColor"] = renderData.getTexture(kColorInput);
    var["gScatterDistance"] = renderData.getTexture(kScatterDistanceInput);
    var["gGuideNormalW"] = renderData.getTexture(kGuideNormalInput);
    var["gSpecRough"] = renderData.getTexture(kSpecRoughInput);
    var["gDiffuseAlbedo"] = renderData.getTexture(kDiffuseAlbedoInput);
    // Slang requires every declared resource to be bound even when the branch using it is off.
    var["gScatterDensity"] = pScatterDensity ? pScatterDensity : renderData.getTexture(kScatterDistanceInput);
    var["gMediumAlpha"] = pMediumAlpha ? pMediumAlpha : renderData.getTexture(kScatterDistanceInput);
    var["gOutDemodDivisor"] = pDivisor ? pDivisor : renderData.getTexture(kDiffuseRadianceHitDistOutput);

    var["gOutNormalRoughness"] = renderData.getTexture(kNormalRoughnessOutput);

#if FALCOR_HAS_NRD4
    if (mShMode)
    {
        // Fail loudly rather than pack an all-zero SH1, which reads as "no directional information"
        // and denoises without complaint.
        ref<Texture> pLightDir = renderData.getTexture(kLightDirInput);
        FALCOR_CHECK(
            pLightDir != nullptr,
            "NRDAdapter: SH mode needs the '{}' input (VolumetricReSTIR.lightDir), but nothing is "
            "connected to it.",
            kLightDirInput
        );
        var["gLightDir"] = pLightDir;
        var["gOutDiffuseSh0"] = pOut;
        var["gOutDiffuseSh1"] = renderData.getTexture(kDiffuseSh1Output);
    }
    else
#endif
    {
        var["gOutDiffuseRadianceHitDist"] = pOut;
    }

    pPass->execute(pRenderContext, uint3(resolution, 1));
}

void NRDAdapter::renderUI(Gui::Widgets& widget)
{
    widget.var("Min reflectance", mMinReflectance, 0.f, 1.f);
    widget.tooltip(
        "Floor on the albedo the radiance is divided by before denoising. Dividing by a near-black "
        "albedo turns a dark pixel into a firefly that the denoiser then smears. Mirrors Falcor's "
        "kNRDMinReflectance.",
        true
    );

    widget.checkbox("Use normal guide", mUseNormalGuide);
    widget.tooltip("Off feeds a constant normal, ablating the geometric guide.", true);

    widget.checkbox("Use scatter distance", mUseScatterDistance);
    widget.tooltip("Off feeds the constant everywhere, ablating the hit-distance guide.", true);

    widget.var("Miss hit distance", mMissHitDistance, 0.f, 10000.f);
    widget.tooltip(
        "Hit distance used where the primary ray met no medium. NRD has no encoding for 'no hit', "
        "and its front-end clamps negatives to zero -- which reads as 'hit immediately'. Keep this "
        "below NRD's denoising range (10000 units).",
        true
    );
}
