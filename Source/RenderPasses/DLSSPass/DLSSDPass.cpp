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

Properties DLSSDPass::getProperties() const
{
    Properties props;
    props[kEnabled] = mEnabled;
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
        mpNGXWrapper = NGXWrapper::acquire(mpDevice, getRuntimeDirectory(), getRuntimeDirectory());

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
    const uint32_t preset =
        mPreset == RenderPreset::D_Transformer         ? NVSDK_NGX_RayReconstruction_Hint_Render_Preset_D
        : mPreset == RenderPreset::E_TransformerLatest ? NVSDK_NGX_RayReconstruction_Hint_Render_Preset_E
                                                       : 0u;

    // Unlike DLSSPass, the display size is simply the bound output's size. No queryOptimalSettings
    // round trip -- the producer decides the render size, and RR reconstructs to whatever the
    // graph allocated.
    mpNGXWrapper->initializeDLSSD(pRenderContext, mInputSize, mOutputSize, mIsHDR, perfQuality, preset);
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
    const auto now = std::chrono::steady_clock::now();
    float frameTimeMs = 0.f;
    if (mLastFrameTime.time_since_epoch().count() != 0)
        frameTimeMs = std::chrono::duration<float, std::milli>(now - mLastFrameTime).count();
    mLastFrameTime = now;

    mpNGXWrapper->evaluateDLSSD(
        pRenderContext, in, /*resetAccumulation*/ false, jitterOffset, motionVectorScale, &worldToView, &viewToClip, frameTimeMs
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

    if (widget.dropdown("Profile", mProfile))
        mRecreate = true;
    if (widget.dropdown("Render preset", mPreset))
        mRecreate = true;
    if (widget.checkbox("HDR input", mIsHDR))
        mRecreate = true;
    widget.checkbox("Relative motion vectors", mMotionVectorsRelative);

    widget.text(fmt::format("Render:  {}x{}", mInputSize.x, mInputSize.y));
    widget.text(fmt::format("Output:  {}x{}", mOutputSize.x, mOutputSize.y));
    if (mpNGXWrapper)
        widget.text(fmt::format("RayReconstruction available: {}", mpNGXWrapper->isRRAvailable()));
}
