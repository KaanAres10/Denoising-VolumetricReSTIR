#pragma once
#include "Falcor.h"
#include "OpenImageDenoise/oidn.hpp"

class OIDNCPUPass : public RenderPass
{
public:
    using SharedPtr = std::shared_ptr<OIDNCPUPass>;
    static SharedPtr create(RenderContext* pRenderContext, const Dictionary& dict);

    virtual std::string getDesc() override { return kDesc; }
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pContext, const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;

    static const char* kDesc;

private:
    OIDNCPUPass(const Dictionary& dict);

    oidn::DeviceRef mDevice;
    oidn::FilterRef mFilter;

    Buffer::SharedPtr mInputBufGPU;
    Buffer::SharedPtr mOutputBufGPU;

    Buffer::SharedPtr mInputBufCPU;
    Buffer::SharedPtr mOutputBufCPU;

    std::vector<float> mInputBuffer;
    std::vector<float> mOutputBuffer;

    ComputePass::SharedPtr    mpConvertTexToBuf;
    FullScreenPass::SharedPtr mpConvertBufToTex;
    Fbo::SharedPtr            mpFbo;

    uint2 mBufferSize = uint2(0, 0);
};
