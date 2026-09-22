/***************************************************************************
 # Motion-compensated temporal accumulation of the medium layer. See MediumAccumulation.h.
 **************************************************************************/
#include "MediumAccumulation.h"

namespace
{
const char kShaderFile[] = "RenderPasses/MediumAccumulation/MediumAccumulation.cs.slang";

const char kColorInput[] = "color";
const char kMotionVecInput[] = "mvec";
const char kCoverageInput[] = "coverage";
const char kOutput[] = "output";
} // namespace

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, MediumAccumulation>();
}

MediumAccumulation::MediumAccumulation(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    for (const auto& [key, value] : props)
    {
        if (key == "enabled")
            mEnabled = value;
        else if (key == "maxFrames")
            mMaxFrames = value;
        else if (key == "disocclusionRatio")
            mDisocclusionRatio = value;
        else
            logWarning("Unknown property '{}' in MediumAccumulation properties.", key);
    }
    mMaxFrames = std::max(1u, mMaxFrames);

    mpPass = ComputePass::create(mpDevice, kShaderFile, "main");
}

Properties MediumAccumulation::getProperties() const
{
    Properties props;
    props["enabled"] = mEnabled;
    props["maxFrames"] = mMaxFrames;
    props["disocclusionRatio"] = mDisocclusionRatio;
    return props;
}

RenderPassReflection MediumAccumulation::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kColorInput, "The medium layer's radiance this frame");
    r.addInput(kMotionVecInput, "The MEDIUM's motion vectors, current -> previous, normalised screen space");
    r.addInput(kCoverageInput, "The medium's coverage, 1 - transmittance");
    r.addOutput(kOutput, "The medium layer averaged along its own motion").format(ResourceFormat::RGBA32Float).bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
    return r;
}

void MediumAccumulation::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pColor = renderData.getTexture(kColorInput);
    auto pOutput = renderData.getTexture(kOutput);
    const uint2 dims = {pColor->getWidth(), pColor->getHeight()};

    // (Re)allocate the history at the colour's size; a new size starts a new history.
    if (!mpHistory[0] || mpHistory[0]->getWidth() != dims.x || mpHistory[0]->getHeight() != dims.y)
    {
        for (int i = 0; i < 2; i++)
        {
            mpHistory[i] = mpDevice->createTexture2D(dims.x, dims.y, ResourceFormat::RGBA32Float, 1, 1, nullptr,
                                                     ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
            mpHistoryCoverage[i] = mpDevice->createTexture2D(dims.x, dims.y, ResourceFormat::R32Float, 1, 1, nullptr,
                                                             ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
        }
        mHistoryValid = false;
    }

    const uint32_t prev = mLatest, next = 1 - mLatest;
    auto var = mpPass->getRootVar();
    var["CB"]["gResolution"] = dims;
    var["CB"]["gHistoryValid"] = mHistoryValid;
    var["CB"]["gEnabled"] = mEnabled;
    var["CB"]["gMaxFrames"] = float(mMaxFrames);
    var["CB"]["gDisocclusionRatio"] = mDisocclusionRatio;
    var["gColor"] = pColor;
    var["gMotionVec"] = renderData.getTexture(kMotionVecInput);
    var["gCoverage"] = renderData.getTexture(kCoverageInput);
    var["gPrevHistory"] = mpHistory[prev];
    var["gPrevCoverage"] = mpHistoryCoverage[prev];
    var["gOutput"] = pOutput;
    var["gHistory"] = mpHistory[next];
    var["gHistoryCoverage"] = mpHistoryCoverage[next];
    mpPass->execute(pRenderContext, uint3(dims, 1));

    mLatest = next;
    mHistoryValid = true;
}

void MediumAccumulation::renderUI(Gui::Widgets& widget)
{
    widget.checkbox("Enabled", mEnabled);
    widget.tooltip("Off = pass the medium layer through untouched.", true);
    widget.var("Max frames", mMaxFrames, 1u, 64u);
    widget.tooltip("The average spans at most this many frames along the medium's motion.", true);
    widget.var("Disocclusion ratio", mDisocclusionRatio, 0.f, 1.f);
    widget.tooltip("Reset where last frame's coverage at the reprojected position is below this times the "
                   "current coverage: medium the camera has only just uncovered.", true);
    if (widget.button("Reset history"))
        mHistoryValid = false;
}
