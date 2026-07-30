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

// Names match NRDPass's input pins so the graph wiring reads directly.
const char kDiffuseRadianceHitDistOutput[] = "diffuseRadianceHitDist";
const char kNormalRoughnessOutput[] = "normWRoughnessMaterialID";

const char kMinReflectance[] = "minReflectance";
const char kMissHitDistance[] = "missHitDistance";
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
    mpPass = ComputePass::create(mpDevice, kShaderFile, "main", defines);
}

Properties NRDAdapter::getProperties() const
{
    Properties props;
    props[kMinReflectance] = mMinReflectance;
    props[kMissHitDistance] = mMissHitDistance;
    props["useScatterDistance"] = mUseScatterDistance;
    props["useNormalGuide"] = mUseNormalGuide;
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

    // RGBA32Float rather than the RGBA16Float NRD outputs: this carries a world-space hit distance
    // in .a alongside undemodulated-range radiance, and half precision would quantise both.
    r.addOutput(kDiffuseRadianceHitDistOutput, "Demodulated diffuse radiance and hit distance")
        .format(ResourceFormat::RGBA32Float)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    // RGB10A2Unorm is required, not preferred: NRD decodes this with NRD_USE_OCT_NORMAL_ENCODING=1,
    // which assumes exactly this layout.
    r.addOutput(kNormalRoughnessOutput, "Oct-encoded normal, linear roughness, material ID")
        .format(ResourceFormat::RGB10A2Unorm)
        .texture2D(sz.x, sz.y)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    return r;
}

void NRDAdapter::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pOut = renderData.getTexture(kDiffuseRadianceHitDistOutput);
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

    auto var = mpPass->getRootVar();
    var["CB"]["gResolution"] = resolution;
    var["CB"]["gMinReflectance"] = mMinReflectance;
    var["CB"]["gMissHitDistance"] = mMissHitDistance;
    var["CB"]["gUseScatterDistance"] = mUseScatterDistance;
    var["CB"]["gUseNormalGuide"] = mUseNormalGuide;

    var["gColor"] = renderData.getTexture(kColorInput);
    var["gScatterDistance"] = renderData.getTexture(kScatterDistanceInput);
    var["gGuideNormalW"] = renderData.getTexture(kGuideNormalInput);
    var["gSpecRough"] = renderData.getTexture(kSpecRoughInput);
    var["gDiffuseAlbedo"] = renderData.getTexture(kDiffuseAlbedoInput);

    var["gOutDiffuseRadianceHitDist"] = pOut;
    var["gOutNormalRoughness"] = renderData.getTexture(kNormalRoughnessOutput);

    mpPass->execute(pRenderContext, uint3(resolution, 1));
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
