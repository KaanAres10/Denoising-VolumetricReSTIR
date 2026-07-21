/***************************************************************************
 # Intel Open Image Denoise (CPU) render pass, ported to Falcor 8.0.
 #
 # Original: Denoising-VolumetricReSTIR (Falcor 4.x). Algorithm/shaders preserved;
 # only the host/engine glue was rewritten for the 8.0 API.
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "Core/Pass/ComputePass.h"
#include "Core/Pass/FullScreenPass.h"
#include "RenderGraph/RenderPass.h"

#include <OpenImageDenoise/oidn.hpp>

#include <limits>
#include <vector>

using namespace Falcor;

class OIDNCPUPass : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(OIDNCPUPass, "OIDNCPUPass", "Intel Open Image Denoise (CPU implementation).");

    static ref<OIDNCPUPass> create(ref<Device> pDevice, const Properties& props) { return make_ref<OIDNCPUPass>(pDevice, props); }

    OIDNCPUPass(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pRenderContext, const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    oidn::DeviceRef mDevice;
    oidn::FilterRef mFilter;

    ref<Buffer> mInputBufGPU;
    ref<Buffer> mOutputBufGPU;

    ref<Buffer> mInputBufCPU;
    ref<Buffer> mOutputBufCPU;

    std::vector<float> mInputBuffer;
    std::vector<float> mOutputBuffer;

    ref<ComputePass> mpConvertTexToBuf;
    ref<FullScreenPass> mpConvertBufToTex;
    ref<Fbo> mpFbo;

    uint2 mBufferSize = uint2(0, 0);

    bool mEnabled = true;
    bool mHdr = true;
    bool mSrgb = false;
    bool mCleanAux = false;
    int mQuality = 3; // 0 default, 1 fast, 2 balanced, 3 high
    int mMaxMemoryMB = -1;
    float mInputScale = std::numeric_limits<float>::quiet_NaN(); // NaN = auto

    void applyFilterSettings();
};
