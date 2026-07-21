/***************************************************************************
 # Intel Open Image Denoise 2.x (CUDA interop) render pass, ported to Falcor 8.0.
 #
 # Original: Denoising-VolumetricReSTIR (Falcor 4.x). Algorithm/shaders preserved;
 # only the host/engine glue was rewritten for the 8.0 API.
 **************************************************************************/
#include "OIDNGPUPass.h"

#include <cmath>

namespace
{
const std::string kSrc = "src";
const std::string kDst = "dst";

const std::string kConvertTexToBufFile = "RenderPasses/OIDNGPUPass/ConvertTexToBuf.cs.slang";
const std::string kConvertBufToTexFile = "RenderPasses/OIDNGPUPass/ConvertBufToTex.ps.slang";

// Property keys (kept identical to the 4.x dictionary keys for script compatibility).
const char kEnabled[] = "mEnabled";
const char kQuality[] = "mQuality";
const char kHdr[] = "mHdr";
const char kSrgb[] = "mSrgb";
const char kInputScale[] = "mInputScale";
const char kCleanAux[] = "mCleanAux";
const char kMaxMemMB[] = "mMaxMemoryMB";

oidn::Quality toOidnQuality(int q)
{
    switch (q)
    {
    default:
        return oidn::Quality::Default;
    case 1:
        return oidn::Quality::Fast;
    case 2:
        return oidn::Quality::Balanced;
    case 3:
        return oidn::Quality::High;
    }
}
} // namespace

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, OIDNGPUPass>();
}

OIDNGPUPass::OIDNGPUPass(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    // Falcor must have a live CUDA context so its shared buffers can be mapped to CUDA
    // device pointers (createInteropBuffer -> getSharedDevicePtr).
    FALCOR_CHECK(mpDevice->initCudaDevice(), "OIDNGPUPass: failed to initialize CUDA device.");

    mDevice = oidn::newDevice(oidn::DeviceType::CUDA);

    const char* errMsg = nullptr;
    if (mDevice.getError(errMsg) != oidn::Error::None)
        logError("OIDNGPUPass: Device creation error: {}", errMsg ? errMsg : "");

    mDevice.commit();

    mFilter = mDevice.newFilter("RT");

    mEnabled = props.get(kEnabled, mEnabled);
    mHdr = props.get(kHdr, mHdr);
    mSrgb = props.get(kSrgb, mSrgb);
    mCleanAux = props.get(kCleanAux, mCleanAux);
    mQuality = props.get(kQuality, mQuality);
    mMaxMemoryMB = props.get(kMaxMemMB, mMaxMemoryMB);
    mInputScale = props.get(kInputScale, mInputScale);

    applyFilterSettings();

    mpConvertTexToBuf = ComputePass::create(mpDevice, kConvertTexToBufFile, "main");
    mpConvertBufToTex = FullScreenPass::create(mpDevice, kConvertBufToTexFile);
    mpFbo = Fbo::create(mpDevice);
}

void OIDNGPUPass::applyFilterSettings()
{
    mFilter.set("hdr", mHdr);
    mFilter.set("srgb", mSrgb);
    mFilter.set("cleanAux", mCleanAux);
    mFilter.set("quality", toOidnQuality(mQuality));
    if (!std::isnan(mInputScale))
        mFilter.set("inputScale", mInputScale);
    if (mMaxMemoryMB >= 0)
        mFilter.set("maxMemoryMB", mMaxMemoryMB);
}

Properties OIDNGPUPass::getProperties() const
{
    Properties props;
    props[kEnabled] = mEnabled;
    props[kHdr] = mHdr;
    props[kSrgb] = mSrgb;
    props[kCleanAux] = mCleanAux;
    props[kQuality] = mQuality;
    props[kMaxMemMB] = mMaxMemoryMB;
    props[kInputScale] = mInputScale;
    return props;
}

RenderPassReflection OIDNGPUPass::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kSrc, "Input noisy image").format(ResourceFormat::RGBA32Float);
    r.addOutput(kDst, "Output denoised image").format(ResourceFormat::RGBA32Float);
    return r;
}

void OIDNGPUPass::renderUI(Gui::Widgets& widget)
{
    widget.checkbox("Enabled", mEnabled);

    if (!mEnabled)
        return;

    widget.checkbox("HDR", mHdr);
    widget.checkbox("sRGB", mSrgb);
    widget.checkbox("Clean Aux", mCleanAux);

    uint32_t quality = (uint32_t)mQuality;
    if (widget.dropdown("Quality", {{0u, "Default"}, {1u, "Fast"}, {2u, "Balanced"}, {3u, "High"}}, quality))
        mQuality = (int)quality;

    widget.var("Max Memory (MB)", mMaxMemoryMB, -1, 65536);
    widget.var("Input Scale", mInputScale);
}

void OIDNGPUPass::releaseInterop()
{
    mInputBuf.free();
    mInputBuf.buffer = nullptr;
    mOutputBuf.free();
    mOutputBuf.buffer = nullptr;
}

void OIDNGPUPass::initInterop(uint32_t width, uint32_t height)
{
    if (mFrameDim.x == width && mFrameDim.y == height && mInputBuf.buffer)
        return;

    releaseInterop();
    mFrameDim = {width, height};

    const size_t numPixels = size_t(width) * height;
    const size_t byteSize = numPixels * 4 * sizeof(float); // RGBA32F, matches RWBuffer<float4>

    mInputBuf = createInteropBuffer(mpDevice, byteSize);
    mOutputBuf = createInteropBuffer(mpDevice, byteSize);
}

void OIDNGPUPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pSrc = renderData.getTexture(kSrc);
    auto pDst = renderData.getTexture(kDst);
    if (!pSrc || !pDst)
        return;

    if (!mEnabled)
    {
        pRenderContext->blit(pSrc->getSRV(), pDst->getRTV());
        return;
    }

    const uint32_t width = pSrc->getWidth();
    const uint32_t height = pSrc->getHeight();

    initInterop(width, height);
    if (!mInputBuf.devicePtr || !mOutputBuf.devicePtr)
        return;

    // GPU: texture -> shared input buffer via ConvertTexToBuf
    {
        auto var = mpConvertTexToBuf->getRootVar();
        var["GlobalCB"]["gStride"] = width;
        var["gInTex"] = pSrc;
        var["gOutBuf"] = mInputBuf.buffer;
        mpConvertTexToBuf->execute(pRenderContext, width, height);
    }

    // Make sure the DX writes are visible to CUDA before OIDN reads the shared buffer.
    pRenderContext->submit(true);

    // CUDA: run OIDN directly on the shared device pointers (no readback).
    mFilter.setImage("color", (void*)mInputBuf.devicePtr, oidn::Format::Float3, width, height, 0, 16);
    mFilter.setImage("output", (void*)mOutputBuf.devicePtr, oidn::Format::Float3, width, height, 0, 16);
    mFilter.commit();
    mFilter.execute();

    const char* errMsg = nullptr;
    if (mDevice.getError(errMsg) != oidn::Error::None)
        logError("OIDNGPUPass: OIDN error: {}", errMsg ? errMsg : "");

    mDevice.sync(); // ensure OIDN is done before DX reads the shared output buffer

    // GPU: shared output buffer -> texture via ConvertBufToTex
    {
        auto var = mpConvertBufToTex->getRootVar();
        var["GlobalCB"]["gStride"] = width;
        var["gInBuf"] = mOutputBuf.buffer;
        mpFbo->attachColorTarget(pDst, 0);
        mpConvertBufToTex->execute(pRenderContext, mpFbo);
    }
}
