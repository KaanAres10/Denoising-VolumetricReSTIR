/***************************************************************************
 # DLSS Ray Reconstruction (DLSS-D) render pass.
 #
 # A separate class from DLSSPass rather than a mode on it, because reflect() differs structurally:
 # eight inputs instead of three. Making them conditional on a mode enum would change graph-visible
 # IO at runtime and force a requestRecompile(), and the one existing instance of that pattern in
 # DLSSPass (IOSize::Fixed) is already known to throw "graph wasn't successfully compiled yet" on
 # the first frame. Keeping the classes separate also means every existing DLSS script provably
 # still builds the untouched Super Resolution pass.
 **************************************************************************/
#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPassHelpers.h"
#include "NGXWrapper.h"
#include <chrono>

using namespace Falcor;

/**
 * DLSS Ray Reconstruction: a neural denoiser that also upscales, replacing a conventional
 * denoiser (OIDN/OptiX/NRD) rather than sitting after one.
 *
 * Takes the usual color/depth/mvec plus four guide buffers describing the surface: diffuse albedo,
 * specular albedo, normals and roughness. Depth is LINEAR view Z (Depth_Type_Linear), which is what
 * VolumetricReSTIR's linearZ output already provides.
 */
class DLSSDPass : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(DLSSDPass, "DLSSDPass", "DLSS Ray Reconstruction (neural denoiser + upscaler).");

    /// Quality profile -- the complete NVSDK_NGX_PerfQuality_Value set. DLAA is native resolution;
    /// use it to measure RR purely as a denoiser, with no upscaling confound.
    ///
    /// The SDK names differ from the names NVIDIA ships in game UIs, and only the latter tell you the
    /// scale factor, so both are recorded here:
    ///
    ///   SDK               UI                  render scale   pixels
    ///   MaxQuality        Quality             1 / 1.5        44%
    ///   Balanced          Balanced            1 / 1.72       34%
    ///   MaxPerf           Performance         1 / 2          25%
    ///   UltraPerformance  Ultra Performance   1 / 3          11%
    ///   UltraQuality      (never shipped)     1 / 1.3        59%
    ///   DLAA              DLAA                1 / 1         100%
    enum class Profile : uint32_t
    {
        MaxPerf,
        Balanced,
        MaxQuality,
        UltraPerformance,
        /// Declared by the SDK but NOT implemented for Ray Reconstruction: feature creation fails
        /// with NVSDK_NGX_Result_FAIL_UnsupportedParameter. Kept so the enum mirrors
        /// NVSDK_NGX_PerfQuality_Value, but selecting it will throw.
        UltraQuality,
        DLAA,
    };

    FALCOR_ENUM_INFO(
        Profile,
        {
            {Profile::MaxPerf, "MaxPerf"},
            {Profile::Balanced, "Balanced"},
            {Profile::MaxQuality, "MaxQuality"},
            {Profile::UltraPerformance, "UltraPerformance"},
            {Profile::UltraQuality, "UltraQuality"},
            {Profile::DLAA, "DLAA"},
        }
    );

    /// Denoising network. Per nvsdk_ngx_defs_dlssd.h (310.7.0) these three are the only meaningful
    /// values for Ray Reconstruction: A/B/C were removed and F..O are all documented "do not use,
    /// reverts to default behavior", so this is the whole search space.
    ///
    /// BOTH live models are transformer-based -- the older convolutional networks were the presets
    /// NVIDIA removed, so there is no CNN to switch to in this SDK.
    ///
    /// Names carry the NVIDIA letter first (that is what their docs and forums use) followed by what
    /// the model actually is, because a bare letter says nothing at a glance -- and the letters mean
    /// something DIFFERENT for Super Resolution, which is an easy and expensive mistake to make.
    enum class RenderPreset : uint32_t
    {
        Default,             ///< Let NGX choose. Measured bit-identical to D at every quality level.
        D_Transformer,       ///< "Default model (transformer)".
        E_TransformerLatest, ///< "Latest transformer model" -- required if a depth-of-field guide is used.
    };

    FALCOR_ENUM_INFO(
        RenderPreset,
        {
            {RenderPreset::Default, "Default"},
            {RenderPreset::D_Transformer, "D_Transformer"},
            {RenderPreset::E_TransformerLatest, "E_TransformerLatest"},
        }
    );

    static ref<DLSSDPass> create(ref<Device> pDevice, const Properties& props) { return make_ref<DLSSDPass>(pDevice, props); }

    DLSSDPass(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void compile(RenderContext* pRenderContext, const CompileData& compileData) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;
    virtual void setScene(RenderContext* pRenderContext, const ref<Scene>& pScene) override { mpScene = pScene; }

private:
    void initializeDLSSD(RenderContext* pRenderContext);

    ref<Scene> mpScene;
    std::shared_ptr<NGXWrapper> mpNGXWrapper;   ///< Shared per-device NGX session.

    bool mEnabled = true;
    Profile mProfile = Profile::DLAA;
    /// Left at E to match every measurement published so far. D scored better at all four profiles
    /// of the first sweep, but that was a single unreplicated run -- do not change this default
    /// until repeats confirm it.
    RenderPreset mPreset = RenderPreset::E_TransformerLatest;
    bool mIsHDR = true;
    /// Falcor motion vectors are normalized [0,1]; NGX wants pixels unless told otherwise.
    bool mMotionVectorsRelative = true;
    float mExposure = 0.f;

    bool mRecreate = true;
    uint2 mInputSize = {};      ///< Render resolution, taken from the bound color input.
    /// Render size a guide-size mismatch was last reported for, so the warning fires once per size
    /// rather than every frame.
    uint2 mWarnedMismatchSize = {0, 0};
    uint2 mOutputSize = {};     ///< Display resolution, taken from the bound output.

    std::chrono::steady_clock::time_point mLastFrameTime{};  ///< For RR's frame-time hint.

    ref<Texture> mpExposure;    ///< 1x1 R32Float, matching DLSSPass' handling.
};

FALCOR_ENUM_REGISTER(DLSSDPass::Profile);
FALCOR_ENUM_REGISTER(DLSSDPass::RenderPreset);
