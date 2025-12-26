#pragma once

#include "Falcor.h"
#include "FalcorExperimental.h"
#include "CudaUtils.h"

using namespace Falcor;

class OptixDenoiserRecent : public RenderPass
{
public:
    using SharedPtr = std::shared_ptr<OptixDenoiserRecent>;

    static SharedPtr create(RenderContext* pRenderContext, const Dictionary& dict);

    virtual std::string getDesc() override;
    virtual Dictionary getScriptingDictionary() override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pContext, const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

    bool getEnabled() const { return mEnabled; }
    void setEnabled(bool enabled) { mEnabled = enabled; }

private:
    OptixDenoiserRecent(const Dictionary& dict);

    bool initializeOptix();

    void setupDenoiser();

    void convertTexToBuf(RenderContext* pContext, const Texture::SharedPtr& tex, const Buffer::SharedPtr& buf, const uint2& size);
    void convertBufToTex(RenderContext* pContext, const Buffer::SharedPtr& buf, const Texture::SharedPtr& tex, const uint2& size);
    void convertMotionVectors(RenderContext* pContext, const Texture::SharedPtr& tex, const Buffer::SharedPtr& buf, const uint2& size);

    bool                        mEnabled = true;           
    bool                        mIsFirstFrame = true;     
    bool                        mHasColorInput = true;
    bool                        mHasAlbedoInput = false;
    bool                        mHasNormalInput = false;
    bool                        mHasMotionInput = false;
    uint2                       mBufferSize = uint2(0, 0);  
    bool                        mRecreateDenoiser = true;  

    Gui::DropdownList           mModelChoices = {};
    uint32_t                    mSelectedModel = OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_TEMPORAL;

    bool                        mOptixInitialized = false;
    OptixDeviceContext          mOptixContext = nullptr;

    struct Interop
    {
        Buffer::SharedPtr       buffer;                       // Falcor buffer
        CUdeviceptr             devicePtr = (CUdeviceptr)0;   // CUDA pointer to buffer
    };

    // Encapsulate denoiser parameters, settings, and state.
    struct
    {
        OptixDenoiserOptions    options = {};
        OptixDenoiserModelKind  modelKind = OptixDenoiserModelKind::OPTIX_DENOISER_MODEL_KIND_TEMPORAL;
        OptixDenoiser           denoiser = nullptr;

        OptixDenoiserParams     params = {};
        OptixDenoiserSizes      sizes = {};

        OptixDenoiserAlphaMode  alphaMode = OPTIX_DENOISER_ALPHA_MODE_COPY;

        bool                    kernelPredictionMode = false;
        bool                    useAOVs = false;
        uint32_t                tileOverlap = 0u;

        uint32_t                tileWidth = 0u;
        uint32_t                tileHeight = 0u;

        // A wrapper around denoiser inputs for guide normals, albedo, and motion vectors
        OptixDenoiserGuideLayer guideLayer = {};

        // A wrapper around denoiser input color, output color, and prior frame's output
        OptixDenoiserLayer      layer = {};

        // A wrapper around our guide layer interop with DirectX
        struct Intermediates
        {
            Interop             normal;
            Interop             albedo;
            Interop             motionVec;
            Interop             denoiserInput;
            Interop             denoiserOutput;
        } interop;

        // GPU memory need to allocate for the Optix denoiser
        CudaBuffer  scratchBuffer, stateBuffer, intensityBuffer, hdrAverageBuffer;

    } mDenoiser;

    // Shaders for converting buffers on input and output from OptiX
    ComputePass::SharedPtr      mpConvertTexToBuf;
    ComputePass::SharedPtr      mpConvertMotionVectors;
    FullScreenPass::SharedPtr   mpConvertBufToTex;
    Fbo::SharedPtr              mpFbo;

    void allocateStagingBuffer(RenderContext* pContext, Interop& interop, OptixImage2D& image, OptixPixelFormat format = OPTIX_PIXEL_FORMAT_FLOAT4);

    void freeStagingBuffer(Interop& interop, OptixImage2D& image);

    void reallocateStagingBuffers(RenderContext* pContext, uint2 newSize);

    void* exportBufferToCudaDevice(Buffer::SharedPtr& buf);
};