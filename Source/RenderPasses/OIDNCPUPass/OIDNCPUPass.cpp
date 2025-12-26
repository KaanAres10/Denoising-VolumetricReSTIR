#include "OIDNCPUPass.h"

const char* OIDNCPUPass::kDesc = "Intel Open Image Denoise (CPU Implementation)";

static const std::string kSrc = "src";
static const std::string kDst = "dst";

static const std::string kConvertTexToBufFile = "RenderPasses/OIDNCPUPass/ConvertTexToBuf.cs.slang";
static const std::string kConvertBufToTexFile = "RenderPasses/OIDNCPUPass/ConvertBufToTex.ps.slang";

extern "C" __declspec(dllexport) const char* getProjDir() { return PROJECT_DIR; }

extern "C" __declspec(dllexport) void getPasses(Falcor::RenderPassLibrary & lib)
{
    lib.registerClass("OIDNCPUPass", OIDNCPUPass::kDesc, OIDNCPUPass::create);
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
    if (!mFilter)
    {
        logError("OIDNCPUPass: Failed to create OIDN RT filter");
    }

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
