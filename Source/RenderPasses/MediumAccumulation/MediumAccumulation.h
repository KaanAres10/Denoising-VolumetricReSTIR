/***************************************************************************
 # Motion-compensated temporal accumulation of the medium layer, ahead of the medium layer's Ray
 # Reconstruction in the two-layer path (vr_graph add_rr_layers, VR_RR_LAYERS=1).
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"

using namespace Falcor;

/**
 * Averages the medium layer over the last few frames along the MEDIUM's own motion vectors, before
 * RR sees it.
 *
 * Why: the medium's thin outer rim reaches the denoiser as sparse bright samples -- ReSTIR keeps one
 * sample per pixel, and where the medium covers little of the pixel that sample is rarely a medium
 * one -- so its light only emerges by averaging over many frames. Here the history follows the medium
 * exactly and keeps averaging while the camera moves.
 *
 * It was built to stop the rim dimming while the camera moves, and does not: that light is missing
 * from its INPUT -- the estimator's temporal reuse loses thin medium at a moving silhouette (see
 * VolumetricReSTIR's mTemporalReprojectIndependent) -- and an average cannot restore it. With that
 * fixed the layer arrives right (0.98 / 0.94 of the true light, thin / edge, bistro stop 3), yet the
 * two-layer image is still ~7-9% dim in motion while one RR is not.
 *
 * The history holds radiance per unit coverage and is fetched bilinearly over the texels that had
 * medium (see the .cs.slang for why); a per-pixel history length is capped at maxFrames; and the
 * history is reset where the reprojection lands where the medium's coverage was much lower last frame
 * -- medium the camera has only just uncovered.
 * Reads only the estimator's outputs, so the estimator itself is untouched.
 */
class MediumAccumulation : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(MediumAccumulation, "MediumAccumulation", "Motion-compensated temporal accumulation of a medium layer.");

    static ref<MediumAccumulation> create(ref<Device> pDevice, const Properties& props)
    {
        return make_ref<MediumAccumulation>(pDevice, props);
    }

    MediumAccumulation(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    ref<ComputePass> mpPass;
    /// Ping-pong history: rgb = accumulated radiance per unit coverage, a = history length in frames.
    ref<Texture> mpHistory[2];
    /// The coverage each history texel was accumulated under, for the disocclusion test.
    ref<Texture> mpHistoryCoverage[2];
    uint32_t mLatest = 0;       ///< which of the pair holds last frame's result
    bool mHistoryValid = false;

    bool mEnabled = true;
    /// Cap on the history length: the average spans at most this many frames.
    uint32_t mMaxFrames = 8;
    /// Reset where last frame's coverage at the reprojected position is below this x the current one.
    float mDisocclusionRatio = 0.5f;
};
