/***************************************************************************
 # DLSS Ray Reconstruction (DLSS-D) render pass. See DLSSDPass.h for why this is a separate class
 # from DLSSPass, and DLSSPass/README.md for the SDK requirement.
 **************************************************************************/
#include "DLSSDPass.h"

#if FALCOR_HAS_DLSSD
// Render-preset enum lives in the DLSS-D defs header.
#include <nvsdk_ngx_defs_dlssd.h>
#endif

namespace
{
const char kColorInput[] = "color";
const char kDepthInput[] = "depth";
const char kMotionVectorsInput[] = "mvec";
const char kDiffuseAlbedoInput[] = "diffuseAlbedo";
const char kSpecularAlbedoInput[] = "specularAlbedo";
const char kNormalsInput[] = "normals";
const char kRoughnessInput[] = "roughness";
const char kOutput[] = "output";

const char kEnabled[] = "enabled";
const char kSDKVariant[] = "sdkVariant";
/// Subdirectory of the runtime directory holding the 310.7.0 feature DLLs. Populated by
/// build_scripts/deploycommon.bat from external/dlss-310; shared with DLSSPass.
const char kPrevious310_7Subdir[] = "dlss_310_7";
const char kProfile[] = "profile";
const char kPreset[] = "preset";
const char kIsHDR[] = "isHDR";
const char kMotionVectorsRelative[] = "motionVectorsRelative";
const char kExposure[] = "exposure";
} // namespace

DLSSDPass::DLSSDPass(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    for (const auto& [key, value] : props)
    {
        if (key == kEnabled)
            mEnabled = value;
        else if (key == kSDKVariant)
            mSDKVariant = value;
        else if (key == kProfile)
            mProfile = value;
        else if (key == kPreset)
            mPreset = value;
        else if (key == kIsHDR)
            mIsHDR = value;
        else if (key == kMotionVectorsRelative)
            mMotionVectorsRelative = value;
        else if (key == kExposure)
            mExposure = value;
        else
            logWarning("Unknown property '{}' in DLSSDPass properties.", key);
    }

    mpExposure = mpDevice->createTexture2D(1, 1, ResourceFormat::R32Float, 1, 1, nullptr, ResourceBindFlags::ShaderResource);
    float exposure = pow(2.f, mExposure);
    mpDevice->getRenderContext()->updateTextureData(mpExposure.get(), &exposure);
}

DLSSDPass::~DLSSDPass()
{
#if FALCOR_HAS_DLSSD
    if (mpNGXWrapper)
        mpNGXWrapper->releaseDLSSD(this);
#endif
}

Properties DLSSDPass::getProperties() const
{
    Properties props;
    props[kEnabled] = mEnabled;
    props[kSDKVariant] = mSDKVariant;
    props[kProfile] = mProfile;
    props[kPreset] = mPreset;
    props[kIsHDR] = mIsHDR;
    props[kMotionVectorsRelative] = mMotionVectorsRelative;
    props[kExposure] = mExposure;
    return props;
}

RenderPassReflection DLSSDPass::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kColorInput, "Color input (linear HDR radiance)").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kDepthInput, "Linear view-space Z").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kMotionVectorsInput, "Motion vectors").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kDiffuseAlbedoInput, "Diffuse albedo guide").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kSpecularAlbedoInput, "Specular albedo guide").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kNormalsInput, "World-space guide normals").bindFlags(ResourceBindFlags::ShaderResource);
    r.addInput(kRoughnessInput, "Roughness guide").bindFlags(ResourceBindFlags::ShaderResource);

    // IOSize::Default only, deliberately. DLSSPass' Fixed mode discovers its output size after NGX
    // init and calls requestRecompile() mid-frame, which Mogwai cannot survive on frame 1.
    r.addOutput(kOutput, "Denoised, reconstructed color")
        .format(ResourceFormat::RGBA32Float)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::RenderTarget);
    return r;
}

void DLSSDPass::compile(RenderContext* pRenderContext, const CompileData& compileData)
{
    mRecreate = true;
}

void DLSSDPass::initializeDLSSD(RenderContext* pRenderContext)
{
    if (!mpNGXWrapper)
    {
        // The feature search path is what selects the DLL, and therefore which networks the preset
        // below chooses between. Same mechanism as DLSSPass' LegacyCNN variant.
        const std::filesystem::path searchPath = mSDKVariant == SDKVariant::Previous310_7
                                                     ? getRuntimeDirectory() / kPrevious310_7Subdir
                                                     : getRuntimeDirectory();
        mpNGXWrapper = NGXWrapper::acquire(mpDevice, getRuntimeDirectory(), searchPath);
    }

#if FALCOR_HAS_DLSSD
    NVSDK_NGX_PerfQuality_Value perfQuality = NVSDK_NGX_PerfQuality_Value_DLAA;
    switch (mProfile)
    {
    case Profile::MaxPerf:
        perfQuality = NVSDK_NGX_PerfQuality_Value_MaxPerf;
        break;
    case Profile::Balanced:
        perfQuality = NVSDK_NGX_PerfQuality_Value_Balanced;
        break;
    case Profile::MaxQuality:
        perfQuality = NVSDK_NGX_PerfQuality_Value_MaxQuality;
        break;
    case Profile::UltraPerformance:
        perfQuality = NVSDK_NGX_PerfQuality_Value_UltraPerformance;
        break;
    case Profile::UltraQuality:
        perfQuality = NVSDK_NGX_PerfQuality_Value_UltraQuality;
        break;
    case Profile::DLAA:
        perfQuality = NVSDK_NGX_PerfQuality_Value_DLAA;
        break;
    }

    // 0 means "no hint": let NGX pick the default network for this quality level.
    //
    // The values are what reach the DLL, as plain integers, whichever SDK's header compiled this --
    // F is declared (as "do not use") in 310.7.0 too. Pin them so a renumbering cannot silently point
    // one variant's letter at another network.
    static_assert(
        NVSDK_NGX_RayReconstruction_Hint_Render_Preset_D == 4 && NVSDK_NGX_RayReconstruction_Hint_Render_Preset_E == 5 &&
            NVSDK_NGX_RayReconstruction_Hint_Render_Preset_F == 6,
        "DLSS Ray Reconstruction render preset values have been renumbered"
    );
    uint32_t preset = 0u;
    switch (mPreset)
    {
    case RenderPreset::D_Transformer: preset = NVSDK_NGX_RayReconstruction_Hint_Render_Preset_D; break;
    case RenderPreset::E_TransformerLatest: preset = NVSDK_NGX_RayReconstruction_Hint_Render_Preset_E; break;
    case RenderPreset::F_RR2: preset = NVSDK_NGX_RayReconstruction_Hint_Render_Preset_F; break;
    case RenderPreset::Default: break;
    }

    // A preset the loaded DLL does not implement does not fail: NGX quietly runs that DLL's default and
    // returns a plausible image of the wrong network, which would corrupt a comparison unnoticed.
    if (mPreset == RenderPreset::F_RR2 && mSDKVariant == SDKVariant::Previous310_7)
        logWarning("DLSSDPass: preset F (RR2) selected with the 310.7.0 SDK variant; that DLL has no RR2 and NGX will run its default (D) instead.");

    // Unlike DLSSPass, the display size is simply the bound output's size. No queryOptimalSettings
    // round trip -- the producer decides the render size, and RR reconstructs to whatever the
    // graph allocated.
    mpNGXWrapper->initializeDLSSD(this, pRenderContext, mInputSize, mOutputSize, mIsHDR, perfQuality, preset);
    mAppliedPresetHint = preset;
#else
    FALCOR_THROW("DLSSDPass requires a DLSS SDK with Ray Reconstruction (see DLSSPass/README.md).");
#endif
    mRecreate = false;
}

void DLSSDPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pColor = renderData.getTexture(kColorInput);
    auto pOutput = renderData.getTexture(kOutput);
    FALCOR_ASSERT(pColor && pOutput);

    if (!mEnabled || !mpScene)
    {
        pRenderContext->blit(pColor->getSRV(), pOutput->getRTV());
        return;
    }

#if FALCOR_HAS_DLSSD
    const uint2 inputSize = {pColor->getWidth(), pColor->getHeight()};
    const uint2 outputSize = {pOutput->getWidth(), pOutput->getHeight()};

    if (mRecreate || any(inputSize != mInputSize) || any(outputSize != mOutputSize))
    {
        mInputSize = inputSize;
        mOutputSize = outputSize;
        initializeDLSSD(pRenderContext);
    }

    // Every input must be pixel-aligned with the colour, because all of the scaling below is derived
    // from the colour's size. A guide at a different resolution is not rejected by NGX -- it is
    // sampled as if it matched, so features land at the wrong place and the result is misregistered
    // edges and silhouette fringing rather than an error. This is easy to hit whenever one pass in
    // the graph is sized from the requested display and another from the actual swapchain, so check
    // rather than trust. Warn once per size combination to avoid a per-frame flood.
    {
        const std::pair<const char*, const Texture*> guides[] = {
            {kDepthInput, renderData.getTexture(kDepthInput).get()},
            {kMotionVectorsInput, renderData.getTexture(kMotionVectorsInput).get()},
            {kDiffuseAlbedoInput, renderData.getTexture(kDiffuseAlbedoInput).get()},
            {kSpecularAlbedoInput, renderData.getTexture(kSpecularAlbedoInput).get()},
            {kNormalsInput, renderData.getTexture(kNormalsInput).get()},
            {kRoughnessInput, renderData.getTexture(kRoughnessInput).get()},
        };
        for (const auto& [name, pTex] : guides)
        {
            if (pTex == nullptr)
                continue;
            const uint2 sz = {pTex->getWidth(), pTex->getHeight()};
            if (any(sz != inputSize) && any(inputSize != mWarnedMismatchSize))
            {
                logWarning(
                    "DLSSDPass: input '{}' is {}x{} but color is {}x{}. Ray Reconstruction assumes all "
                    "inputs share the render resolution; mismatched guides misregister and show as "
                    "silhouette/edge artifacts. Size every producing pass from the same source.",
                    name, sz.x, sz.y, inputSize.x, inputSize.y
                );
                mWarnedMismatchSize = inputSize;
            }
        }
    }

    NGXWrapper::DLSSDEvalInputs in;
    in.color = pColor.get();
    in.output = pOutput.get();
    in.depth = renderData.getTexture(kDepthInput).get();
    in.motionVectors = renderData.getTexture(kMotionVectorsInput).get();
    in.diffuseAlbedo = renderData.getTexture(kDiffuseAlbedoInput).get();
    in.specularAlbedo = renderData.getTexture(kSpecularAlbedoInput).get();
    in.normals = renderData.getTexture(kNormalsInput).get();
    in.roughness = renderData.getTexture(kRoughnessInput).get();
    in.exposure = mpExposure.get();

    // Jitter sign matches DLSSPass: Falcor's projection has Y running bottom-to-top while DLSS
    // wants top-to-bottom, so only Y is flipped. Offsets are in render-pixel space.
    const auto& camera = mpScene->getCamera();
    float2 jitterOffset = float2(camera->getJitterX(), -camera->getJitterY()) * float2(inputSize);

    // Our motion vectors are normalized [0,1]; NGX scales them to pixels itself.
    float2 motionVectorScale = mMotionVectorsRelative ? float2(inputSize) : float2(1.f, 1.f);

    // Supply the camera matrices and frame time. RR uses the matrices for reprojection beyond what
    // depth+mvec express, and scales denoising strength by the speed implied by frame time against
    // motion-vector magnitude. NoJitter variants: the jitter is reported separately above, so a
    // jittered projection would double-count it.
    const float4x4 worldToView = camera->getViewMatrix();
    const float4x4 viewToClip = camera->getData().projMatNoJitter;

    // Wall-clock delta. A render pass has no access to Mogwai's clock, and RR only needs this as a
    // hint for how much motion a frame represents, so measuring it here is sufficient.
    //
    // MEASURED INERT (2026-09-18, bistro orbit, 40 frames at 960x540): RR's output is bit-identical
    // whether this is the wall clock, a fixed 33.3 ms (matching a clock pinned at 30 fps) or 500 ms,
    // for 310.7.0 preset E and 310.9.1 preset F alike. So a mismatch with a pinned scene clock costs
    // nothing, and the gain once credited to "matrices and frame time" is the matrices'.
    const auto now = std::chrono::steady_clock::now();
    float frameTimeMs = 0.f;
    if (mLastFrameTime.time_since_epoch().count() != 0)
        frameTimeMs = std::chrono::duration<float, std::milli>(now - mLastFrameTime).count();
    mLastFrameTime = now;

    mpNGXWrapper->evaluateDLSSD(
        this, pRenderContext, in, /*resetAccumulation*/ false, jitterOffset, motionVectorScale, &worldToView, &viewToClip, frameTimeMs
    );
#else
    pRenderContext->blit(pColor->getSRV(), pOutput->getRTV());
#endif
}

void DLSSDPass::renderUI(Gui::Widgets& widget)
{
    widget.checkbox("Enabled", mEnabled);
    if (!mEnabled)
        return;

    widget.dropdown("SDK variant", mSDKVariant);
    widget.tooltip(
        "Which nvngx_dlssd.dll NGX loads: Current = the DLL beside the executable (310.9.1, presets D/E/F), "
        "Previous310_7 = 310.7.0 (presets D/E; no RR2). Read only when the NGX session is first created -- "
        "changing it needs a restart, so compare the two as separate runs. The log line "
        "'[NGX] loaded nvngx_dlssd.dll version ...' reports what is really running.",
        true
    );
    if (widget.dropdown("Profile", mProfile))
        mRecreate = true;
    if (widget.dropdown("Render preset", mPreset))
        mRecreate = true;
    widget.tooltip(
        "Ray Reconstruction network. F = RR2, the default in 310.9.1. D and E are transformer models. "
        "These letters are NOT the same networks as the Super Resolution presets of the same name.",
        true
    );
    if (widget.checkbox("HDR input", mIsHDR))
        mRecreate = true;
    widget.checkbox("Relative motion vectors", mMotionVectorsRelative);

    widget.text(fmt::format("Render:  {}x{}", mInputSize.x, mInputSize.y));
    widget.text(fmt::format("Output:  {}x{}", mOutputSize.x, mOutputSize.y));
    if (mpNGXWrapper)
    {
        widget.text(fmt::format("RayReconstruction available: {}", mpNGXWrapper->isRRAvailable()));
        // What is actually running, read back rather than taken from the dropdowns: the DLL NGX
        // mapped (the SDK variant is only a search-path hint) and the hint the feature was created
        // with. Letters per nvsdk_ngx_defs_dlssd.h: 4 = D, 5 = E, 6 = F.
        if (!mpNGXWrapper->getLoadedRRVersion().empty())
        {
            const char* letter = mAppliedPresetHint == 4   ? "D"
                                 : mAppliedPresetHint == 5 ? "E"
                                 : mAppliedPresetHint == 6 ? "F (RR2)"
                                 : mAppliedPresetHint == 0 ? "Default"
                                                           : "?";
            widget.text(fmt::format(
                "Running: nvngx_dlssd.dll {}, preset {} (hint {})", mpNGXWrapper->getLoadedRRVersion(), letter, mAppliedPresetHint
            ));
        }
    }
}
