#pragma once
#include "Falcor.h"
#include <OpenImageDenoise/oidn.hpp>

using namespace Falcor;

class OIDNGPUPass : public RenderPass
{
public:
    using SharedPtr = std::shared_ptr<OIDNGPUPass>;
    static const char* kDesc;

    static SharedPtr create(RenderContext* pRenderContext, const Dictionary& dict);

    std::string getDesc() override { return kDesc; }
    Dictionary getScriptingDictionary() override;
    RenderPassReflection reflect(const CompileData& compileData) override;
    void execute(RenderContext* pRenderContext, const RenderData& renderData) override;

private:
    OIDNGPUPass(const Dictionary& dict);

    void renderUI(Gui::Widgets& widget) override;


    void initInterop(RenderContext* pCtx, uint32_t width, uint32_t height);
    void releaseInterop();
    // OIDN
    oidn::DeviceRef mDevice;
    oidn::FilterRef mFilter;

    // Falcor Buffers
    Buffer::SharedPtr mInputBuf;
    Buffer::SharedPtr mOutputBuf;

    void* mExtMemIn = nullptr;
    void* mExtMemOut = nullptr;
    void* mCudaDevPtrIn = nullptr;
    void* mCudaDevPtrOut = nullptr;

    Falcor::uint2 mFrameDim = { 0, 0 }; 

    ComputePass::SharedPtr    mpConvertTexToBuf;
    FullScreenPass::SharedPtr mpConvertBufToTex;
    Fbo::SharedPtr            mpFbo;

    bool  mEnabled = true;
    bool  mHdr = true;
    bool  mSrgb = false;
    bool  mCleanAux = false;
    int   mQuality = 3; // 0 default, 1 fast, 2 balanced, 3 high
    int   mMaxMemoryMB = -1;
    float mInputScale = std::numeric_limits<float>::quiet_NaN(); // NaN = auto
};