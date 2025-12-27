#include "OIDNCPUPass.h"

const char* OIDNCPUPass::kDesc = "Intel Open Image Denoise (CPU Implementation)";

static const std::string kSrc = "src";
static const std::string kDst = "dst";

static const std::string kConvertTexToBufFile = "RenderPasses/OIDNCPUPass/ConvertTexToBuf.cs.slang";
static const std::string kConvertBufToTexFile = "RenderPasses/OIDNCPUPass/ConvertBufToTex.ps.slang";

// dict keys
static const char kEnabled[] = "mEnabled";
static const char kQuality[] = "mQuality";
static const char kHdr[] = "mHdr";
static const char kSrgb[] = "mSrgb";
static const char kInputScale[] = "mInputScale";
static const char kCleanAux[] = "mCleanAux";
static const char kMaxMemMB[] = "mMaxMemoryMB";


extern "C" __declspec(dllexport) const char* getProjDir() { return PROJECT_DIR; }

extern "C" __declspec(dllexport) void getPasses(Falcor::RenderPassLibrary & lib)
{
    lib.registerClass("OIDNCPUPass", OIDNCPUPass::kDesc, OIDNCPUPass::create);
}

static oidn::Quality toOidnQuality(int q)
{
    switch (q)
    {
    default: return oidn::Quality::Default;
    case 1:  return oidn::Quality::Fast;
    case 2:  return oidn::Quality::Balanced;
    case 3:  return oidn::Quality::High;
    }
}


OIDNCPUPass::SharedPtr OIDNCPUPass::create(RenderContext* pRenderContext, const Dictionary& dict)
{
    return SharedPtr(new OIDNCPUPass(dict));
}

OIDNCPUPass::OIDNCPUPass(const Dictionary& dict)
{
    mDevice = oidn::newDevice(oidn::DeviceType::CPU);

    const char* errMsg = nullptr;
    if (mDevice.getError(errMsg) != oidn::Error::None)
    {
        logError(std::string("OIDNCPUPass: Device creation error: ") + (errMsg ? errMsg : ""));
    }

    mDevice.commit();

    mFilter = mDevice.newFilter("RT");

    if (dict.keyExists(kEnabled))    mEnabled = (bool)dict[kEnabled];
    if (dict.keyExists(kHdr))        mHdr = (bool)dict[kHdr];
    if (dict.keyExists(kSrgb))       mSrgb = (bool)dict[kSrgb];
    if (dict.keyExists(kCleanAux))   mCleanAux = (bool)dict[kCleanAux];
    if (dict.keyExists(kQuality))    mQuality = (int)dict[kQuality];
    if (dict.keyExists(kMaxMemMB))   mMaxMemoryMB = (int)dict[kMaxMemMB];
    if (dict.keyExists(kInputScale)) mInputScale = (float)dict[kInputScale];

    mFilter.set("hdr", mHdr);
    mFilter.set("srgb", mSrgb);
    mFilter.set("cleanAux", mCleanAux);
    mFilter.set("quality", toOidnQuality(mQuality));
    if (!std::isnan(mInputScale))
        mFilter.set("inputScale", mInputScale);

    if (mMaxMemoryMB >= 0)
        mFilter.set("maxMemoryMB", mMaxMemoryMB);

    mpConvertTexToBuf = ComputePass::create(kConvertTexToBufFile, "main");
    mpConvertBufToTex = FullScreenPass::create(kConvertBufToTexFile);
    mpFbo = Fbo::create();
}

RenderPassReflection OIDNCPUPass::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kSrc, "Input noisy image")
        .format(ResourceFormat::RGBA32Float);   
    r.addOutput(kDst, "Output denoised image")
        .format(ResourceFormat::RGBA32Float);   
    return r;
}

Dictionary OIDNCPUPass::getScriptingDictionary()
{
    Dictionary d;
    d[kEnabled] = mEnabled;
    d[kHdr] = mHdr;
    d[kSrgb] = mSrgb;
    d[kCleanAux] = mCleanAux;
    d[kQuality] = mQuality;
    d[kMaxMemMB] = mMaxMemoryMB;
    d[kInputScale] = mInputScale;
    return d;
}

void OIDNCPUPass::renderUI(Gui::Widgets& widget)
{
    widget.checkbox("Enabled", mEnabled);

    if (!mEnabled) return;

    widget.checkbox("HDR", mHdr);
    widget.checkbox("sRGB", mSrgb);
    widget.checkbox("Clean Aux", mCleanAux);

    uint32_t quality = (uint32_t)mQuality;

    if (widget.dropdown(
        "Quality",
        {
            {0u, "Default"},
            {1u, "Fast"},
            {2u, "Balanced"},
            {3u, "High"}
        },
        quality))
    {
        mQuality = (int)quality;
    }
    widget.var("Max Memory (MB)", mMaxMemoryMB, -1, 65536); // pick bounds you like
    widget.var("Input Scale", mInputScale);                // beware NaN, see note below
}

static void allocateStagingBuffers(RenderContext* pContext,
    uint2 newSize,
    Buffer::SharedPtr& inBufGPU,
    Buffer::SharedPtr& outBufGPU,
    Buffer::SharedPtr& inBufCPU,
    Buffer::SharedPtr& outBufCPU)
{
    const uint32_t numPixels = newSize.x * newSize.y;


    const Resource::BindFlags gpuFlags =
        Resource::BindFlags::ShaderResource |
        Resource::BindFlags::UnorderedAccess;

    inBufGPU = Buffer::createTyped(
        ResourceFormat::RGBA32Float,
        numPixels,
        gpuFlags,
        Buffer::CpuAccess::None
    );

    outBufGPU = Buffer::createTyped(
        ResourceFormat::RGBA32Float,
        numPixels,
        gpuFlags,
        Buffer::CpuAccess::None
    );

    const Resource::BindFlags cpuFlags = Resource::BindFlags::None;

    inBufCPU = Buffer::createTyped(
        ResourceFormat::RGBA32Float,
        numPixels,
        cpuFlags,
        Buffer::CpuAccess::Read
    );

    outBufCPU = Buffer::createTyped(
        ResourceFormat::RGBA32Float,
        numPixels,
        cpuFlags,
        Buffer::CpuAccess::Write
    );
}


void OIDNCPUPass::compile(RenderContext* pContext, const CompileData& compileData)
{
    uint2 newSize = compileData.defaultTexDims;
    if (newSize.x == 0 || newSize.y == 0) return;

    if (newSize != mBufferSize)
    {
        mBufferSize = newSize;
        allocateStagingBuffers(pContext, mBufferSize,
            mInputBufGPU, mOutputBufGPU,
            mInputBufCPU, mOutputBufCPU);
    }
}


void OIDNCPUPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    auto pSrc = renderData[kSrc]->asTexture();
    auto pDst = renderData[kDst]->asTexture();
    if (!pSrc || !pDst ||
        !mInputBufGPU || !mOutputBufGPU ||
        !mInputBufCPU || !mOutputBufCPU) return;

    if (!mEnabled)
    {
        pRenderContext->blit(pSrc->getSRV(), pDst->getRTV());
        return;
    }

    const size_t numPixels = size_t(mBufferSize.x) * mBufferSize.y;
    const size_t numFloats = numPixels * 4;

    // GPU: texture -> GPU input buffer via ConvertTexToBuf
    {
        auto vars = mpConvertTexToBuf->getVars();
        vars["GlobalCB"]["gStride"] = mBufferSize.x;
        vars["gInTex"] = pSrc;
        vars["gOutBuf"] = mInputBufGPU;
        mpConvertTexToBuf->execute(pRenderContext, mBufferSize.x, mBufferSize.y);
    }

    //  GPU: copy GPU input buffer -> CPU staging input buffer
    pRenderContext->copyResource(mInputBufCPU.get(), mInputBufGPU.get());
    pRenderContext->flush(true); // ensure copy is done before we map

    // CPU: map input, run OIDN, write to CPU output buffer
    {
        float* inPtr = (float*)mInputBufCPU->map(Buffer::MapType::Read);
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

        mFilter.setImage("color",
            mInputBuffer.data(),
            oidn::Format::Float3,
            mBufferSize.x, mBufferSize.y,
            0, pixelStride, rowStride);

        mFilter.setImage("output",
            mOutputBuffer.data(),
            oidn::Format::Float3,
            mBufferSize.x, mBufferSize.y,
            0, pixelStride, rowStride);

        mFilter.set("hdr", true);
        mFilter.set("srgb", false);

        mFilter.commit();
        mFilter.execute();

        const char* errMsg = nullptr;
        auto err = mDevice.getError(errMsg);
        if (err != oidn::Error::None)
        {
            logError("OIDNCPUPass: OIDN error = " + std::to_string(int(err)) +
                " msg = " + (errMsg ? std::string(errMsg) : ""));
            mOutputBuffer = mInputBuffer;
        }

        for (size_t i = 0; i < numPixels; ++i)
        {
            mOutputBuffer[i * 4 + 3] = 1.0f;
        }

        float* outCPUPtr = (float*)mOutputBufCPU->map(Buffer::MapType::WriteDiscard);
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
        auto vars = mpConvertBufToTex->getVars();
        vars["GlobalCB"]["gStride"] = mBufferSize.x;
        vars["gInBuf"] = mOutputBufGPU;
        mpFbo->attachColorTarget(pDst, 0);
        mpConvertBufToTex->execute(pRenderContext, mpFbo);
    }
}
