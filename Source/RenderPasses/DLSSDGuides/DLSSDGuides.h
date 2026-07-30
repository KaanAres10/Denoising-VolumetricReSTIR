/***************************************************************************
 # Converts G-buffer channels into DLSS Ray Reconstruction guide buffers. See the .cs.slang for why
 # the conversion is needed at all.
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"
#include "RenderGraph/RenderPassHelpers.h"

using namespace Falcor;

/**
 * Produces the four surface guide buffers DLSS Ray Reconstruction consumes -- diffuse albedo,
 * pre-integrated specular albedo, world-space normals and roughness -- from Falcor's G-buffer.
 *
 * Kept separate from DLSSDPass so each guide can be markOutput'd and eyeballed in Mogwai when RR
 * misbehaves, and so Stage 2's volumetric blending lands here without touching the NGX pass.
 */
class DLSSDGuides : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(DLSSDGuides, "DLSSDGuides", "Builds DLSS Ray Reconstruction guide buffers from a G-buffer.");

    static ref<DLSSDGuides> create(ref<Device> pDevice, const Properties& props) { return make_ref<DLSSDGuides>(pDevice, props); }

    DLSSDGuides(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    ref<ComputePass> mpPass;
    /// Floor on reflectance guides; mirrors kNRDMinReflectance in the PathTracer's NRD helpers.
    float mMinReflectance = 0.01f;
    /// Single-scatter albedo sigma_s/sigma_t of the medium. Uniform: only density varies spatially.
    /// Default matches the Bistro plume (sigma_s=80, sigma_a=10 -> 80/90).
    float3 mMediumScatterAlbedo = float3(0.888f, 0.888f, 0.888f);

    /// Guide resolution. MUST match the colour fed to DLSSDPass -- see reflect().
    RenderPassHelpers::IOSize mOutputSizeSelection = RenderPassHelpers::IOSize::Default;
    uint2 mFixedOutputSize = {512, 512};
    /// Ratio of the display, as on VolumetricReSTIR and GBufferBase. Preferred over a fixed size for
    /// upscaling setups: a fixed size is computed from a *requested* display resolution, which the
    /// window manager need not honour (fullscreen), whereas the ratio resolves against the real one.
    /// Mutable so reflect() (const) can adopt the graph-wide scale. See Falcor::getRenderScale().
    mutable bool mUpscaling = false;
    mutable float mUpscaleRatio = 0.58f;
    mutable uint32_t mRenderScaleGen = 0;

    /// Which guides the medium blend is applied to, for attributing the gain to individual guides.
    bool mBlendDiffuse = true;
    bool mBlendSpecular = true;
    bool mBlendRoughness = true;
    bool mBlendNormal = true;
    /// Multiplier on medium coverage. 0 reproduces the surface-only path exactly.
    float mAlphaScale = 1.f;
    /// Blend target for roughness; 1 = fully rough (isotropic).
    float mMediumRoughness = 1.f;

    /// Replace a guide with a neutral constant, to measure RR without the information it carries.
    /// RR requires all four inputs, so they are neutralised rather than disconnected.
    bool mNeutralDiffuse = false;
    bool mNeutralSpecular = false;
    bool mNeutralRoughness = false;
    bool mNeutralNormal = false;
};
