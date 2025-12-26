#include "OptixDenoiserRecent.h"
#include "CudaUtils.h"
namespace
{
    const char kDesc[] = "Apply the OptiX 9.0+ AI Denoiser";

    const char kColorInput[] = "color";
    const char kAlbedoInput[] = "albedo";
    const char kNormalInput[] = "normal";
    const char kMotionInput[] = "mvec";
    const char kOutput[] = "output";

    const char kEnabled[] = "enabled";
    const char kBlend[] = "blend";
    const char kDenoiseAlpha[] = "denoiseAlpha";

    const std::string kConvertTexToBufFile = "RenderPasses/OptixDenoiserRecent/ConvertTexToBuf.cs.slang";
    const std::string kConvertMotionVecFile = "RenderPasses/OptixDenoiserRecent/ConvertMotionVectorInputs.cs.slang";
    const std::string kConvertBufToTexFile = "RenderPasses/OptixDenoiserRecent/ConvertBufToTex.ps.slang";

    const Falcor::Resource::BindFlags   kSharedBufferFlags = Resource::BindFlags::ShaderResource | Resource::BindFlags::UnorderedAccess | Resource::BindFlags::RenderTarget | Resource::BindFlags::Shared;
};

static void regOptixDenoiserRecent(pybind11::module& m)
{
    pybind11::class_<OptixDenoiserRecent, RenderPass, OptixDenoiserRecent::SharedPtr> pass(m, "OptixDenoiserRecent");
    pass.def_property(kEnabled, &OptixDenoiserRecent::getEnabled, &OptixDenoiserRecent::setEnabled);
}

extern "C" __declspec(dllexport) const char* getProjDir()
{
    return PROJECT_DIR;
}

extern "C" __declspec(dllexport) void getPasses(Falcor::RenderPassLibrary & lib)
{
    lib.registerClass("OptixDenoiserRecent", kDesc, OptixDenoiserRecent::create);
    ScriptBindings::registerBinding(regOptixDenoiserRecent);
}

OptixDenoiserRecent::OptixDenoiserRecent(const Dictionary& dict)
{
    // Default alpha mode
    mDenoiser.alphaMode = OPTIX_DENOISER_ALPHA_MODE_COPY;
    mDenoiser.params.blendFactor = 0.0f;

    for (const auto& [key, value] : dict)
    {
        if (key == kEnabled) mEnabled = value;
        else if (key == kBlend) mDenoiser.params.blendFactor = value;
        else if (key == kDenoiseAlpha)
        {
            mDenoiser.alphaMode = (value) ? OPTIX_DENOISER_ALPHA_MODE_DENOISE : OPTIX_DENOISER_ALPHA_MODE_COPY;
        }
       else if (key == "model")
        {
            uint32_t modelIndex = (uint32_t)value;
            switch (modelIndex)
            {
            case 0: // LDR
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_LDR;
                break;
            case 1: // HDR
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_HDR;
                break;
            case 2: // AOV
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_AOV;
                break;
            case 3: // UPSCALE 2X
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_UPSCALE2X;
                break;
            case 4: // TEMPORAL
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_TEMPORAL;
                break;
            default:
                logWarning("Unknown model index " + std::to_string(modelIndex) + ". Defaulting to Temporal.");
                mSelectedModel = OPTIX_DENOISER_MODEL_KIND_TEMPORAL;
                break;
            }
            mDenoiser.modelKind = static_cast<OptixDenoiserModelKind>(mSelectedModel);
        }
        else logWarning("Unknown field '" + key + "' in a OptixDenoiserRecent dictionary");
    }

    mpConvertTexToBuf = ComputePass::create(kConvertTexToBufFile, "main");
    mpConvertMotionVectors = ComputePass::create(kConvertMotionVecFile, "main");
    mpConvertBufToTex = FullScreenPass::create(kConvertBufToTexFile);
    mpFbo = Fbo::create();
}

OptixDenoiserRecent::SharedPtr OptixDenoiserRecent::create(RenderContext* pRenderContext, const Dictionary& dict)
{
    return SharedPtr(new OptixDenoiserRecent(dict));
}

std::string OptixDenoiserRecent::getDesc() { return kDesc; }

Dictionary OptixDenoiserRecent::getScriptingDictionary()
{
    Dictionary d;
    d[kEnabled] = mEnabled;
    d[kBlend] = mDenoiser.params.blendFactor;
    d[kDenoiseAlpha] = (mDenoiser.alphaMode == OPTIX_DENOISER_ALPHA_MODE_DENOISE);

    return d;
}

RenderPassReflection OptixDenoiserRecent::reflect(const CompileData& compileData)
{
    RenderPassReflection r;
    r.addInput(kColorInput, "Color input");
    r.addInput(kAlbedoInput, "Albedo input").flags(RenderPassReflection::Field::Flags::Optional);
    r.addInput(kNormalInput, "Normal input").flags(RenderPassReflection::Field::Flags::Optional);
    r.addInput(kMotionInput, "Motion vector input").flags(RenderPassReflection::Field::Flags::Optional);
    r.addOutput(kOutput, "Denoised output").format(ResourceFormat::RGBA32Float);
    return r;
}

void OptixDenoiserRecent::compile(RenderContext* pContext, const CompileData& compileData)
{
    if (!initializeOptix()) { return; }

    // Determine available inputs
    mHasColorInput = (compileData.connectedResources.getField(kColorInput) != nullptr);
    mHasAlbedoInput = (compileData.connectedResources.getField(kAlbedoInput) != nullptr);
    mHasNormalInput = (compileData.connectedResources.getField(kNormalInput) != nullptr);
    mHasMotionInput = (compileData.connectedResources.getField(kMotionInput) != nullptr);

    // Set correct parameters for the provided inputs.
    mDenoiser.options.guideNormal = mHasNormalInput ? 1u : 0u;
    mDenoiser.options.guideAlbedo = mHasAlbedoInput ? 1u : 0u;

    // Create a dropdown menu for selecting the denoising mode
    mModelChoices = {};
    mModelChoices.push_back({ OPTIX_DENOISER_MODEL_KIND_LDR, "LDR denoising" });
    mModelChoices.push_back({ OPTIX_DENOISER_MODEL_KIND_HDR, "HDR denoising" });

    mModelChoices.push_back({ OPTIX_DENOISER_MODEL_KIND_AOV, "AOV denoising" });

    mModelChoices.push_back({ OPTIX_DENOISER_MODEL_KIND_UPSCALE2X, "Upscale 2X" });

    if (mHasMotionInput)
    {
        mModelChoices.push_back({ OPTIX_DENOISER_MODEL_KIND_TEMPORAL, "Temporal denoising" });
    }

    // Reallocate temporary buffers when render resolution changes
    uint2 newSize = compileData.defaultTexDims;
    mDenoiser.tileWidth = newSize.x;
    mDenoiser.tileHeight = newSize.y;

    if (newSize != mBufferSize && newSize.x > 0 && newSize.y > 0)
    {
        reallocateStagingBuffers(pContext, newSize);
    }

    // Resize intensity and hdrAverage buffers.
    mDenoiser.intensityBuffer.resize(1 * sizeof(float));
    mDenoiser.hdrAverageBuffer.resize(3 * sizeof(float));

    // Initialize params pointers
    if (!mDenoiser.kernelPredictionMode || !mDenoiser.useAOVs)
    {
        mDenoiser.params.hdrIntensity = mDenoiser.intensityBuffer.getDevicePtr();
        mDenoiser.params.hdrAverageColor = static_cast<CUdeviceptr>(0);
    }
    else
    {
        mDenoiser.params.hdrIntensity = static_cast<CUdeviceptr>(0);
        mDenoiser.params.hdrAverageColor = mDenoiser.hdrAverageBuffer.getDevicePtr();
    }

    mRecreateDenoiser = true;
}

void OptixDenoiserRecent::reallocateStagingBuffers(RenderContext* pContext, uint2 newSize)
{
    mBufferSize = newSize;

    allocateStagingBuffer(pContext, mDenoiser.interop.denoiserInput, mDenoiser.layer.input);
    allocateStagingBuffer(pContext, mDenoiser.interop.denoiserOutput, mDenoiser.layer.output);

    if (mDenoiser.options.guideNormal > 0)
        allocateStagingBuffer(pContext, mDenoiser.interop.normal, mDenoiser.guideLayer.normal);
    else
        freeStagingBuffer(mDenoiser.interop.normal, mDenoiser.guideLayer.normal);

    if (mDenoiser.options.guideAlbedo > 0)
        allocateStagingBuffer(pContext, mDenoiser.interop.albedo, mDenoiser.guideLayer.albedo);
    else
        freeStagingBuffer(mDenoiser.interop.albedo, mDenoiser.guideLayer.albedo);

    if (mHasMotionInput)
        allocateStagingBuffer(pContext, mDenoiser.interop.motionVec, mDenoiser.guideLayer.flow, OPTIX_PIXEL_FORMAT_FLOAT2);
    else
        freeStagingBuffer(mDenoiser.interop.motionVec, mDenoiser.guideLayer.flow);
}

void OptixDenoiserRecent::allocateStagingBuffer(RenderContext* pContext, Interop& interop, OptixImage2D& image, OptixPixelFormat format)
{
    uint32_t elemSize = 4 * sizeof(float);
    ResourceFormat falcorFormat = ResourceFormat::RGBA32Float;
    switch (format)
    {
    case OPTIX_PIXEL_FORMAT_FLOAT4:
        elemSize = 4 * sizeof(float);
        falcorFormat = ResourceFormat::RGBA32Float;
        break;
    case OPTIX_PIXEL_FORMAT_FLOAT2:
        elemSize = 2 * sizeof(float);
        falcorFormat = ResourceFormat::RG32Float;
        break;
    default:
        logError("OptixDenoiserRecent called allocateStagingBuffer() with unsupported format!");
        return;
    }

    if (interop.devicePtr) freeSharedDevicePtr((void*)interop.devicePtr);

    interop.buffer = Buffer::createTyped(falcorFormat, mBufferSize.x * mBufferSize.y, kSharedBufferFlags);
    interop.devicePtr = (CUdeviceptr)exportBufferToCudaDevice(interop.buffer);

    image.width = mBufferSize.x;
    image.height = mBufferSize.y;
    image.rowStrideInBytes = mBufferSize.x * elemSize;
    image.pixelStrideInBytes = elemSize;
    image.format = format;
    image.data = interop.devicePtr;
}

void OptixDenoiserRecent::freeStagingBuffer(Interop& interop, OptixImage2D& image)
{
    if (interop.devicePtr) freeSharedDevicePtr((void*)interop.devicePtr);
    interop.buffer = nullptr;
    image.data = static_cast<CUdeviceptr>(0);
}

void OptixDenoiserRecent::execute(RenderContext* pContext, const RenderData& data)
{
    if (mEnabled)
    {
        if (mRecreateDenoiser)
        {
            if (!mHasMotionInput && mDenoiser.modelKind == OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_TEMPORAL)
            {
                mSelectedModel = OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_HDR;
                mDenoiser.modelKind = OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_HDR;
            }

            setupDenoiser();
            mRecreateDenoiser = false;
            mIsFirstFrame = true;
        }

        // Copy input textures to buffers
        convertTexToBuf(pContext, data[kColorInput]->asTexture(), mDenoiser.interop.denoiserInput.buffer, mBufferSize);
        if (mDenoiser.options.guideAlbedo) convertTexToBuf(pContext, data[kAlbedoInput]->asTexture(), mDenoiser.interop.albedo.buffer, mBufferSize);
        if (mDenoiser.options.guideNormal) convertTexToBuf(pContext, data[kNormalInput]->asTexture(), mDenoiser.interop.normal.buffer, mBufferSize);
        if (mDenoiser.modelKind == OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_TEMPORAL)
        {
            convertMotionVectors(pContext, data[kMotionInput]->asTexture(), mDenoiser.interop.motionVec.buffer, mBufferSize);
        }

        pContext->flush(true);

        // Compute average intensity
        if (mDenoiser.params.hdrIntensity)
        {
            optixDenoiserComputeIntensity(
                mDenoiser.denoiser,
                nullptr, 
                &mDenoiser.layer.input,
                mDenoiser.params.hdrIntensity,
                mDenoiser.scratchBuffer.getDevicePtr(),
                mDenoiser.scratchBuffer.getSize()
            );
        }

        // Compute average color
        if (mDenoiser.params.hdrAverageColor)
        {
            optixDenoiserComputeAverageColor(
                mDenoiser.denoiser,
                nullptr, 
                &mDenoiser.layer.input,
                mDenoiser.params.hdrAverageColor,
                mDenoiser.scratchBuffer.getDevicePtr(),
                mDenoiser.scratchBuffer.getSize()
            );
        }

        if (mIsFirstFrame)
        {
            mDenoiser.layer.previousOutput = mDenoiser.layer.input;
        }

        // Run denoiser
        optixDenoiserInvoke(mDenoiser.denoiser,
            nullptr,               
            &mDenoiser.params,
            mDenoiser.stateBuffer.getDevicePtr(), mDenoiser.stateBuffer.getSize(),
            &mDenoiser.guideLayer,
            &mDenoiser.layer,
            1u,                     
            0u,                     
            0u,                      
            mDenoiser.scratchBuffer.getDevicePtr(), mDenoiser.scratchBuffer.getSize());

        cudaDeviceSync();

        convertBufToTex(pContext, mDenoiser.interop.denoiserOutput.buffer, data[kOutput]->asTexture(), mBufferSize);

        if (mIsFirstFrame)
        {
            mDenoiser.layer.previousOutput = mDenoiser.layer.output;
            mIsFirstFrame = false;
        }
    }
    else
    {
        pContext->blit(data[kColorInput]->asTexture()->getSRV(), data[kOutput]->asTexture()->getRTV());
    }
}

void OptixDenoiserRecent::renderUI(Gui::Widgets& widget)
{
    widget.checkbox("Use OptiX Denoiser?", mEnabled);

    if (mEnabled)
    {
        if (widget.dropdown("Model", mModelChoices, mSelectedModel))
        {
            mDenoiser.modelKind = static_cast<OptixDenoiserModelKind>(mSelectedModel);
            mRecreateDenoiser = true;
        }
        widget.tooltip("Selects the OptiX denosing model.");

        if (mHasAlbedoInput)
        {
            bool useAlbedoGuide = mDenoiser.options.guideAlbedo != 0u;
            if (widget.checkbox("Use albedo guide?", useAlbedoGuide))
            {
                mDenoiser.options.guideAlbedo = useAlbedoGuide ? 1u : 0u;
                mRecreateDenoiser = true;
            }
        }

        if (mHasNormalInput)
        {
            bool useNormalGuide = mDenoiser.options.guideNormal != 0u;
            if (widget.checkbox("Use normal guide?", useNormalGuide))
            {
                mDenoiser.options.guideNormal = useNormalGuide ? 1u : 0u;
                mRecreateDenoiser = true;
            }
            widget.tooltip("Use input, noise-free normal buffer to help guide denoising.");
        }

        {
            bool denoiseAlpha = (mDenoiser.alphaMode == OPTIX_DENOISER_ALPHA_MODE_DENOISE);
            if (widget.checkbox("Denoise Alpha?", denoiseAlpha))
            {
                mDenoiser.alphaMode = denoiseAlpha ? OPTIX_DENOISER_ALPHA_MODE_DENOISE : OPTIX_DENOISER_ALPHA_MODE_COPY;
                mRecreateDenoiser = true;
            }
            widget.tooltip("Enable denoising the alpha channel. Requires recreating the denoiser in OptiX 9.0+.");
        }

        widget.slider("Blend", mDenoiser.params.blendFactor, 0.f, 1.f);
        widget.tooltip("Blend between denoised and original input. (0 = denoised only, 1 = noisy only)");
    }
}

void* OptixDenoiserRecent::exportBufferToCudaDevice(Buffer::SharedPtr& buf)
{
    if (buf == nullptr) return nullptr;
    return getSharedDevicePtr(buf->createSharedApiHandle(), (uint32_t)buf->getSize());
}

bool OptixDenoiserRecent::initializeOptix()
{
    if (!mOptixInitialized) mOptixInitialized = initOptix(mOptixContext) >= 0;
    return mOptixInitialized;
}

void OptixDenoiserRecent::setupDenoiser()
{
    if (mDenoiser.denoiser)
    {
        optixDenoiserDestroy(mDenoiser.denoiser);
    }

    mDenoiser.options.denoiseAlpha = mDenoiser.alphaMode;

    // Create the denoiser
    optixDenoiserCreate(mOptixContext,
        mDenoiser.modelKind,
        &mDenoiser.options,
        &mDenoiser.denoiser);

    // Compute memory resources
    optixDenoiserComputeMemoryResources(mDenoiser.denoiser, mDenoiser.tileWidth, mDenoiser.tileHeight, &mDenoiser.sizes);

    // Allocate/resize internal buffers
    mDenoiser.scratchBuffer.resize(mDenoiser.sizes.withoutOverlapScratchSizeInBytes);
    mDenoiser.stateBuffer.resize(mDenoiser.sizes.stateSizeInBytes);

    optixDenoiserSetup(mDenoiser.denoiser,
        nullptr,
        mDenoiser.tileWidth + 2 * mDenoiser.tileOverlap,
        mDenoiser.tileHeight + 2 * mDenoiser.tileOverlap,
        mDenoiser.stateBuffer.getDevicePtr(), mDenoiser.stateBuffer.getSize(),
        mDenoiser.scratchBuffer.getDevicePtr(), mDenoiser.scratchBuffer.getSize());
}

void OptixDenoiserRecent::convertMotionVectors(RenderContext* pContext, const Texture::SharedPtr& tex, const Buffer::SharedPtr& buf, const uint2& size)
{
    auto vars = mpConvertMotionVectors->getVars();
    vars["GlobalCB"]["gStride"] = size.x;
    vars["GlobalCB"]["gSize"] = size;
    vars["gInTex"] = tex;
    vars["gOutBuf"] = buf;
    mpConvertMotionVectors->execute(pContext, size.x, size.y);
}

void OptixDenoiserRecent::convertTexToBuf(RenderContext* pContext, const Texture::SharedPtr& tex, const Buffer::SharedPtr& buf, const uint2& size)
{
    auto vars = mpConvertTexToBuf->getVars();
    vars["GlobalCB"]["gStride"] = size.x;
    vars["gInTex"] = tex;
    vars["gOutBuf"] = buf;
    mpConvertTexToBuf->execute(pContext, size.x, size.y);
}

void OptixDenoiserRecent::convertBufToTex(RenderContext* pContext, const Buffer::SharedPtr& buf, const Texture::SharedPtr& tex, const uint2& size)
{
    auto vars = mpConvertBufToTex->getVars();
    vars["GlobalCB"]["gStride"] = size.x;
    vars["gInBuf"] = buf;
    mpFbo->attachColorTarget(tex, 0);
    mpConvertBufToTex->execute(pContext, mpFbo);
}