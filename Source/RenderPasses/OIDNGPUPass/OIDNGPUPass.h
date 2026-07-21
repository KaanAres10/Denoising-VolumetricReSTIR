/***************************************************************************
 # Intel Open Image Denoise 2.x (CUDA interop) render pass, ported to Falcor 8.0.
 #
 # Original: Denoising-VolumetricReSTIR (Falcor 4.x). Algorithm/shaders preserved;
 # only the host/engine glue was rewritten for the 8.0 API. The fork's hand-rolled
 # D3D12<->CUDA interop (OIDNCudaInterop.*) is replaced by Falcor 8.0's shared
 # InteropBuffer (Utils/CudaUtils.h), which the native OptixDenoiser pass also uses.
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "Core/Pass/ComputePass.h"
#include "Core/Pass/FullScreenPass.h"
#include "RenderGraph/RenderPass.h"
#include "Utils/CudaUtils.h"

#include <OpenImageDenoise/oidn.hpp>

#include <limits>

using namespace Falcor;

class OIDNGPUPass : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(OIDNGPUPass, "OIDNGPUPass", "Intel Open Image Denoise 2.x (CUDA interop).");

    static ref<OIDNGPUPass> create(ref<Device> pDevice, const Properties& props) { return make_ref<OIDNGPUPass>(pDevice, props); }

    OIDNGPUPass(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    void initInterop(uint32_t width, uint32_t height);
    void releaseInterop();
    void applyFilterSettings();

    // OIDN
    oidn::DeviceRef mDevice;
    oidn::FilterRef mFilter;

    // DX <-> CUDA shared buffers (Falcor buffer + CUDA device pointer).
    InteropBuffer mInputBuf;
    InteropBuffer mOutputBuf;

    uint2 mFrameDim = {0, 0};

    ref<ComputePass> mpConvertTexToBuf;
    ref<FullScreenPass> mpConvertBufToTex;
    ref<Fbo> mpFbo;

    bool mEnabled = true;
    bool mHdr = true;
    bool mSrgb = false;
    bool mCleanAux = false;
    int mQuality = 3; // 0 default, 1 fast, 2 balanced, 3 high
    int mMaxMemoryMB = -1;
    float mInputScale = std::numeric_limits<float>::quiet_NaN(); // NaN = auto
};
