/***************************************************************************
 # Builds NRD RELAX guide buffers from this renderer's volumetric output. See NRDAdapter.cs.slang.
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"
#include "RenderGraph/RenderPassHelpers.h"

using namespace Falcor;

/**
 * Kept separate from NRDPass so the volumetric-specific conversion is testable on its own: every
 * output can be markOutput'd and inspected when NRD produces something unexpected.
 */
class NRDAdapter : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(NRDAdapter, "NRDAdapter", "Builds NRD RELAX guide buffers from volumetric ReSTIR output.");

    static ref<NRDAdapter> create(ref<Device> pDevice, const Properties& props) { return make_ref<NRDAdapter>(pDevice, props); }

    NRDAdapter(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    ref<ComputePass> mpPass;
#if FALCOR_HAS_NRD4
    ref<ComputePass> mpShPass;
    ref<ComputePass>& getPass() { return mShMode ? mpShPass : mpPass; }
#else
    ref<ComputePass>& getPass() { return mpPass; }
#endif

    /// Floor on the demodulation divisor; mirrors Falcor's kNRDMinReflectance.
    float mMinReflectance = 0.01f;
    /// Hit distance substituted where the ray met no medium. Must stay under NRD's denoisingRange.
    float mMissHitDistance = 1000.f;
    /// Feed the real scatter distance, or the constant everywhere (ablation).
    bool mUseScatterDistance = true;
    /// Feed the real surface normal, or a constant (ablation).
    bool mUseNormalGuide = true;
#if FALCOR_HAS_NRD4
    /// Emit the SH0/SH1 pair for NRD v4's RELAX_DIFFUSE_SH instead of packed radiance+hitDist.
    /// Changes what reflect() declares, so toggling it needs a graph recompile.
    bool mShMode = false;
#endif

    /// Guide resolution. Must match the colour handed to NRD, exactly as for the DLSS guides.
    RenderPassHelpers::IOSize mOutputSizeSelection = RenderPassHelpers::IOSize::Default;
    uint2 mFixedOutputSize = {512, 512};
    /// Graph-wide render scale; see Falcor::getRenderScale().
    mutable bool mUpscaling = false;
    mutable float mUpscaleRatio = 0.58f;
    mutable uint32_t mRenderScaleGen = 0;

    /// Render size a size mismatch was last reported for, so the warning fires once per size.
    uint2 mWarnedMismatchSize = {0, 0};
};
