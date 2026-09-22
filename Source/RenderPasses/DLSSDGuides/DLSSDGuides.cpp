/***************************************************************************
 # Converts G-buffer channels into DLSS Ray Reconstruction guide buffers.
 **************************************************************************/
#include "DLSSDGuides.h"

namespace
{
const char kShaderFile[] = "RenderPasses/DLSSDGuides/DLSSDGuides.cs.slang";

const char kDiffuseOpacityInput[] = "diffuseOpacity";
const char kSpecRoughInput[] = "specRough";
const char kGuideNormalInput[] = "guideNormalW";
const char kViewWInput[] = "viewW";

const char kDiffuseAlbedoOutput[] = "diffuseAlbedo";
const char kSpecularAlbedoOutput[] = "specularAlbedo";
const char kNormalsOutput[] = "normals";
const char kRoughnessOutput[] = "roughness";

const char kMediumAlphaInput[] = "mediumAlpha";
const char kMediumNormalInput[] = "mediumNormal";

// Two-layer path (layer = Surface): the layer's radiance in, divided by transmittance out, plus the
// exact divisor so the composite can multiply back by the same number.
const char kColorInput[] = "color";
const char kColorDemodOutput[] = "colorDemod";
const char kDemodDivisorOutput[] = "demodDivisor";

const char* layerName(DLSSDGuides::Layer l)
{
    return l == DLSSDGuides::Layer::Surface ? "Surface" : l == DLSSDGuides::Layer::Medium ? "Medium" : "Blend";
}

const char kMinReflectance[] = "minReflectance";
const char kMediumScatterAlbedo[] = "mediumScatterAlbedo";
} // namespace

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, DLSSDGuides>();
}

DLSSDGuides::DLSSDGuides(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    for (const auto& [key, value] : props)
    {
        if (key == kMinReflectance)
            mMinReflectance = value;
        else if (key == kMediumScatterAlbedo)
            mMediumScatterAlbedo = value;
        else if (key == "blendDiffuse")
            mBlendDiffuse = value;
        else if (key == "blendSpecular")
            mBlendSpecular = value;
        else if (key == "blendRoughness")
            mBlendRoughness = value;
        else if (key == "blendNormal")
            mBlendNormal = value;
        else if (key == "alphaScale")
            mAlphaScale = value;
        else if (key == "mediumRoughness")
            mMediumRoughness = value;
        else if (key == "neutralDiffuse")
            mNeutralDiffuse = value;
        else if (key == "neutralSpecular")
            mNeutralSpecular = value;
        else if (key == "neutralRoughness")
            mNeutralRoughness = value;
        else if (key == "neutralNormal")
            mNeutralNormal = value;
        else if (key == "skyDefaults")
            mSkyDefaults = value;
        else if (key == "outputSize")
            mOutputSizeSelection = value;
        else if (key == "fixedOutputSize")
            mFixedOutputSize = value;
        else if (key == "upscale")
            mUpscaling = value;
        else if (key == "upscaleRatio")
            mUpscaleRatio = value;
        else if (key == "layer")
        {
            const std::string s = value;
            if (s == "Blend") mLayer = Layer::Blend;
            else if (s == "Surface") mLayer = Layer::Surface;
            else if (s == "Medium") mLayer = Layer::Medium;
            else logWarning("DLSSDGuides: unknown layer '{}' (expected Blend|Surface|Medium)", s);
        }
        else if (key == "minTransmittance")
            mMinTransmittance = value;
        else if (key == "mediumAlbedoByCoverage")
            mMediumAlbedoByCoverage = value;
        else
            logWarning("Unknown property '{}' in DLSSDGuides properties.", key);
    }

    mpPass = ComputePass::create(mpDevice, kShaderFile, "main");
}

Properties DLSSDGuides::getProperties() const
{
    Properties props;
    props[kMinReflectance] = mMinReflectance;
    props[kMediumScatterAlbedo] = mMediumScatterAlbedo;
    props["blendDiffuse"] = mBlendDiffuse;
    props["blendSpecular"] = mBlendSpecular;
    props["blendRoughness"] = mBlendRoughness;
    props["blendNormal"] = mBlendNormal;
    props["alphaScale"] = mAlphaScale;
    props["mediumRoughness"] = mMediumRoughness;
    props["neutralDiffuse"] = mNeutralDiffuse;
    props["neutralSpecular"] = mNeutralSpecular;
    props["neutralRoughness"] = mNeutralRoughness;
    props["neutralNormal"] = mNeutralNormal;
    props["skyDefaults"] = mSkyDefaults;
    props["outputSize"] = mOutputSizeSelection;
    if (mOutputSizeSelection == RenderPassHelpers::IOSize::Fixed)
        props["fixedOutputSize"] = mFixedOutputSize;
    props["upscale"] = mUpscaling;
    if (mUpscaling)
        props["upscaleRatio"] = mUpscaleRatio;
    props["layer"] = std::string(layerName(mLayer));
    props["minTransmittance"] = mMinTransmittance;
    props["mediumAlbedoByCoverage"] = mMediumAlbedoByCoverage;
    return props;
}

RenderPassReflection DLSSDGuides::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kDiffuseOpacityInput, "Diffuse reflection albedo and opacity (GBuffer diffuseOpacity)");
    r.addInput(kSpecRoughInput, "Specular reflectance (F0) and roughness (GBuffer specRough)");
    r.addInput(kGuideNormalInput, "World-space guide normal (GBuffer guideNormalW)");
    r.addInput(kViewWInput, "World-space view vector (GBuffer viewW)");
    // Optional: when connected, guides are blended toward medium-like values by the coverage.
    r.addInput(kMediumAlphaInput, "Medium coverage, 1 - transmittance").flags(RenderPassReflection::Field::Flags::Optional);
    r.addInput(kMediumNormalInput, "Medium stand-in normal").flags(RenderPassReflection::Field::Flags::Optional);

    // Size the outputs to the RENDER resolution, not the graph default. Left at the default they are
    // allocated at swapchain size while the inputs are at render size, so with upscaling enabled RR
    // receives guides misregistered by exactly the upscale factor -- which appears as silhouette and
    // edge fringing rather than as an error, because RR samples them as though they matched.
    //
    // Taken from an explicit property rather than inferred from the connected input: CompileData's
    // connectedResources is documented as possibly empty during compilation, and it did come back
    // empty here. Mirroring GBufferBase's outputSize/fixedOutputSize means one number configures the
    // estimator, the G-buffer and the guides together.
    // Adopt the graph-wide render scale (see GBufferBase::resolveOutputSize).
    if (getRenderScale().generation != mRenderScaleGen)
    {
        mRenderScaleGen = getRenderScale().generation;
        mUpscaling = getRenderScale().enabled;
        mUpscaleRatio = getRenderScale().ratio;
    }

    uint2 sz;
    if (mUpscaling)
    {
        // Same rounding as VolumetricReSTIR::upscaledRenderSize and GBufferBase::resolveOutputSize.
        const float ratio = std::clamp(mUpscaleRatio, 0.25f, 1.f);
        sz = uint2(uint32_t(compileData.defaultTexDims.x * ratio), uint32_t(compileData.defaultTexDims.y * ratio));
        sz = uint2(std::max(sz.x / 2 * 2, 32u), std::max(sz.y / 2 * 2, 32u));
    }
    else
    {
        sz = RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mFixedOutputSize, compileData.defaultTexDims);
    }

    r.addOutput(kDiffuseAlbedoOutput, "Diffuse albedo guide").format(ResourceFormat::RGBA16Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    r.addOutput(kSpecularAlbedoOutput, "Pre-integrated specular albedo guide").format(ResourceFormat::RGBA16Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    r.addOutput(kNormalsOutput, "World-space normal guide").format(ResourceFormat::RGBA16Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    r.addOutput(kRoughnessOutput, "Roughness guide (unpacked)").format(ResourceFormat::R16Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    // Two-layer path, layer = Surface: RR's colour for the surface layer and the divisor to undo it.
    // Float32 like the estimator's colour: the divided values can be large where transmittance is low.
    r.addInput(kColorInput, "Layer radiance to divide by transmittance (layer = Surface)").flags(RenderPassReflection::Field::Flags::Optional);
    r.addOutput(kColorDemodOutput, "Layer radiance / max(transmittance, minTransmittance)").format(ResourceFormat::RGBA32Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource).flags(RenderPassReflection::Field::Flags::Optional);
    r.addOutput(kDemodDivisorOutput, "The divisor used, for re-modulation after denoising").format(ResourceFormat::RGBA16Float).texture2D(sz.x, sz.y).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource).flags(RenderPassReflection::Field::Flags::Optional);
    return r;
}

void DLSSDGuides::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pDiffuseAlbedo = renderData.getTexture(kDiffuseAlbedoOutput);
    FALCOR_ASSERT(pDiffuseAlbedo);
    const uint2 resolution = {pDiffuseAlbedo->getWidth(), pDiffuseAlbedo->getHeight()};

    auto var = mpPass->getRootVar();
    var["CB"]["gResolution"] = resolution;
    var["CB"]["gMinReflectance"] = mMinReflectance;

    // Blend only when BOTH volumetric guides are actually connected; an optional input with no
    // producer is never allocated, and binding a null texture would fault.
    auto pMediumAlpha = renderData.getTexture(kMediumAlphaInput);
    auto pMediumNormal = renderData.getTexture(kMediumNormalInput);
    const bool blendMedium = pMediumAlpha != nullptr && pMediumNormal != nullptr;
    var["CB"]["gBlendMedium"] = blendMedium;
    var["CB"]["gMediumScatterAlbedo"] = mMediumScatterAlbedo;
    var["CB"]["gBlendDiffuse"] = mBlendDiffuse;
    var["CB"]["gBlendSpecular"] = mBlendSpecular;
    var["CB"]["gBlendRoughness"] = mBlendRoughness;
    var["CB"]["gBlendNormal"] = mBlendNormal;
    var["CB"]["gAlphaScale"] = mAlphaScale;
    var["CB"]["gMediumRoughness"] = mMediumRoughness;
    var["CB"]["gNeutralDiffuse"] = mNeutralDiffuse;
    var["CB"]["gNeutralSpecular"] = mNeutralSpecular;
    var["CB"]["gNeutralRoughness"] = mNeutralRoughness;
    var["CB"]["gNeutralNormal"] = mNeutralNormal;
    var["CB"]["gSkyDefaults"] = mSkyDefaults;
    if (pMediumAlpha) var["gMediumAlpha"] = pMediumAlpha;
    if (pMediumNormal) var["gMediumNormal"] = pMediumNormal;

    // Layer mode. Surface and Medium both need the medium's coverage (the transmittance divisor, the
    // medium's albedo); Medium also needs its normal. Fall back to Blend's behaviour without them.
    uint32_t layer = (uint32_t)mLayer;
    if (mLayer == Layer::Surface && !pMediumAlpha)
        layer = (uint32_t)Layer::Blend;
    if (mLayer == Layer::Medium && !blendMedium)
    {
        logWarning("DLSSDGuides: layer=Medium needs mediumAlpha and mediumNormal connected; using Blend.");
        layer = (uint32_t)Layer::Blend;
    }
    var["CB"]["gLayer"] = layer;
    var["CB"]["gMinTransmittance"] = mMinTransmittance;
    var["CB"]["gMediumAlbedoByCoverage"] = mMediumAlbedoByCoverage;
    auto pColor = renderData.getTexture(kColorInput);
    auto pColorDemod = renderData.getTexture(kColorDemodOutput);
    auto pDivisor = renderData.getTexture(kDemodDivisorOutput);
    const bool demod = pColor && pColorDemod && pDivisor && pMediumAlpha;
    var["CB"]["gDemodColor"] = demod;
    if (demod)
    {
        var["gColor"] = pColor;
        var["gOutColorDemod"] = pColorDemod;
        var["gOutDemodDivisor"] = pDivisor;
    }

    var["gDiffuseOpacity"] = renderData.getTexture(kDiffuseOpacityInput);
    var["gSpecRough"] = renderData.getTexture(kSpecRoughInput);
    var["gGuideNormalW"] = renderData.getTexture(kGuideNormalInput);
    var["gViewW"] = renderData.getTexture(kViewWInput);

    var["gOutDiffuseAlbedo"] = pDiffuseAlbedo;
    var["gOutSpecularAlbedo"] = renderData.getTexture(kSpecularAlbedoOutput);
    var["gOutNormals"] = renderData.getTexture(kNormalsOutput);
    var["gOutRoughness"] = renderData.getTexture(kRoughnessOutput);

    mpPass->execute(pRenderContext, uint3(resolution, 1));
}

void DLSSDGuides::renderUI(Gui::Widgets& widget)
{
    widget.text(fmt::format("Layer: {}", layerName(mLayer)));
    widget.tooltip("Blend = guides for the composited pixel (one RR). Surface / Medium = one layer each of "
                   "the two-layer path (VR_RR_LAYERS=1). Set when the graph is built.", true);
    widget.var("Min reflectance", mMinReflectance, 0.f, 1.f);
    widget.tooltip(
        "Floor applied to the albedo guides. A zero guide makes the denoiser demodulate by nothing, "
        "producing fireflies on black materials. Mirrors kNRDMinReflectance.",
        true
    );
    widget.checkbox("Sky defaults", mSkyDefaults);
    widget.tooltip(
        "No-geometry pixels get NVIDIA's documented sky guides (diffuse 0.5, specular/normal/roughness 0) "
        "instead of the G-buffer's cleared zeros, which reached RR as diffuse 0.01 and NaN normals. "
        "Off reproduces the RR numbers recorded before this existed.",
        true
    );

    if (auto group = widget.group("Volumetric blend", true))
    {
        group.var("Medium scatter albedo", mMediumScatterAlbedo, 0.f, 1.f);
        group.tooltip("sigma_s / sigma_t of the participating medium. Constant per volume in this renderer.", true);

        group.var("Coverage scale", mAlphaScale, 0.f, 1.f);
        group.tooltip(
            "Multiplies the medium's coverage (1 - transmittance). At 0 every guide is bit-identical "
            "to the surface-only path, which is the cheapest check that the volumetric path is live: "
            "if 0 and 1 give the same image, it is not running.",
            true
        );

        group.var("Medium roughness", mMediumRoughness, 0.f, 1.f);
        group.tooltip("Roughness the medium blends toward. 1 = isotropic, which stops RR sharpening smoke into streaks.", true);

        group.text("Apply the blend to:");
        group.checkbox("Diffuse albedo", mBlendDiffuse);
        group.checkbox("Specular albedo", mBlendSpecular, true);
        group.checkbox("Roughness", mBlendRoughness);
        group.checkbox("Normals", mBlendNormal, true);
        group.tooltip("Switch guides off individually to attribute the improvement -- the four are not equally important.", true);
    }

    if (auto group = widget.group("Guide ablation"))
    {
        group.text("Replace a guide with a neutral constant:");
        group.checkbox("Neutral diffuse (0.5 grey)", mNeutralDiffuse);
        group.checkbox("Neutral specular (0)", mNeutralSpecular);
        group.checkbox("Neutral roughness (1)", mNeutralRoughness);
        group.checkbox("Neutral normals (camera-facing)", mNeutralNormal);
        group.tooltip(
            "Measures what Ray Reconstruction does WITHOUT the information a guide carries. Not the "
            "same as disconnecting it: RR requires all four inputs, so a well-formed but "
            "uninformative constant is substituted instead.",
            true
        );
    }
}
