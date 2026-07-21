/***************************************************************************
 # Intel Open Image Denoise (CPU) render pass, ported to Falcor 8.0.
 #
 # Original: Denoising-VolumetricReSTIR (Falcor 4.x). Algorithm/shaders preserved;
 # only the host/engine glue was rewritten for the 8.0 API.
 **************************************************************************/
#include "OIDNCPUPass.h"

#include <cmath>
#include <cstring>

namespace
{
const std::string kSrc = "src";
const std::string kDst = "dst";

const std::string kConvertTexToBufFile = "RenderPasses/OIDNCPUPass/ConvertTexToBuf.cs.slang";
const std::string kConvertBufToTexFile = "RenderPasses/OIDNCPUPass/ConvertBufToTex.ps.slang";

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
    registry.registerClass<RenderPass, OIDNCPUPass>();
}

OIDNCPUPass::OIDNCPUPass(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    mDevice = oidn::newDevice(oidn::DeviceType::CPU);

    const char* errMsg = nullptr;
    if (mDevice.getError(errMsg) != oidn::Error::None)
        logError("OIDNCPUPass: Device creation error: {}", errMsg ? errMsg : "");

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

void OIDNCPUPass::applyFilterSettings()
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

Properties OIDNCPUPass::getProperties() const
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

RenderPassReflection OIDNCPUPass::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kSrc, "Input noisy image").format(ResourceFormat::RGBA32Float);
    r.addOutput(kDst, "Output denoised image").format(ResourceFormat::RGBA32Float);
    return r;
}

void OIDNCPUPass::compile(RenderContext* pRenderContext, const CompileData& compileData)
{
    uint2 newSize = compileData.defaultTexDims;
    if (newSize.x == 0 || newSize.y == 0)
        return;

    if (any(newSize != mBufferSize))
    {
        mBufferSize = newSize;
        const uint32_t numPixels = mBufferSize.x * mBufferSize.y;
        const ResourceBindFlags gpuFlags = ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess;

        mInputBufGPU = mpDevice->createTypedBuffer(ResourceFormat::RGBA32Float, numPixels, gpuFlags, MemoryType::DeviceLocal);
        mOutputBufGPU = mpDevice->createTypedBuffer(ResourceFormat::RGBA32Float, numPixels, gpuFlags, MemoryType::DeviceLocal);
        // CPU-visible staging buffers (ReadBack for readback, Upload for write-then-copy).
        mInputBufCPU = mpDevice->createTypedBuffer(ResourceFormat::RGBA32Float, numPixels, ResourceBindFlags::None, MemoryType::ReadBack);
        mOutputBufCPU = mpDevice->createTypedBuffer(ResourceFormat::RGBA32Float, numPixels, ResourceBindFlags::None, MemoryType::Upload);
    }
}

void OIDNCPUPass::renderUI(Gui::Widgets& widget)
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

void OIDNCPUPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pSrc = renderData.getTexture(kSrc);
    auto pDst = renderData.getTexture(kDst);
    if (!pSrc || !pDst || !mInputBufGPU || !mOutputBufGPU || !mInputBufCPU || !mOutputBufCPU)
        return;

    if (!mEnabled)
    {
        pRenderContext->blit(pSrc->getSRV(), pDst->getRTV());
        return;
    }

    const size_t numPixels = size_t(mBufferSize.x) * mBufferSize.y;
    const size_t numFloats = numPixels * 4;

    // GPU: texture -> GPU input buffer via ConvertTexToBuf
    {
        auto var = mpConvertTexToBuf->getRootVar();
        var["GlobalCB"]["gStride"] = mBufferSize.x;
        var["gInTex"] = pSrc;
        var["gOutBuf"] = mInputBufGPU;
        mpConvertTexToBuf->execute(pRenderContext, mBufferSize.x, mBufferSize.y);
    }

    // GPU: copy GPU input buffer -> CPU staging input buffer
    pRenderContext->copyResource(mInputBufCPU.get(), mInputBufGPU.get());
    pRenderContext->submit(true); // ensure copy is done before we map

    // CPU: map input, run OIDN, write to CPU output buffer
    {
        const float* inPtr = (const float*)mInputBufCPU->map();
        if (!inPtr)
        {
            logError("OIDNCPUPass: Failed to map input CPU buffer");
            return;
        }

        mInputBuffer.resize(numFloats);
        std::memcpy(mInputBuffer.data(), inPtr, numFloats * sizeof(float));
        mInputBufCPU->unmap();

        // Run OIDN
        mOutputBuffer.resize(numFloats);

        const size_t pixelStride = sizeof(float) * 4;
        const size_t rowStride = 0;

        mFilter.setImage("color", mInputBuffer.data(), oidn::Format::Float3, mBufferSize.x, mBufferSize.y, 0, pixelStride, rowStride);
        mFilter.setImage("output", mOutputBuffer.data(), oidn::Format::Float3, mBufferSize.x, mBufferSize.y, 0, pixelStride, rowStride);

        mFilter.set("hdr", true);
        mFilter.set("srgb", false);

        mFilter.commit();
        mFilter.execute();

        const char* errMsg = nullptr;
        auto err = mDevice.getError(errMsg);
        if (err != oidn::Error::None)
        {
            logError("OIDNCPUPass: OIDN error = {} msg = {}", int(err), errMsg ? errMsg : "");
            mOutputBuffer = mInputBuffer;
        }

        for (size_t i = 0; i < numPixels; ++i)
            mOutputBuffer[i * 4 + 3] = 1.0f;

        float* outCPUPtr = (float*)mOutputBufCPU->map();
        if (!outCPUPtr)
        {
            logError("OIDNCPUPass: Failed to map output CPU buffer");
            return;
        }

        std::memcpy(outCPUPtr, mOutputBuffer.data(), numFloats * sizeof(float));
        mOutputBufCPU->unmap();
    }

    // GPU: CPU output buffer -> GPU output buffer
    pRenderContext->copyResource(mOutputBufGPU.get(), mOutputBufCPU.get());

    // GPU: GPU output buffer -> texture via ConvertBufToTex
    {
        auto var = mpConvertBufToTex->getRootVar();
        var["GlobalCB"]["gStride"] = mBufferSize.x;
        var["gInBuf"] = mOutputBufGPU;
        mpFbo->attachColorTarget(pDst, 0);
        mpConvertBufToTex->execute(pRenderContext, mpFbo);
    }
}
