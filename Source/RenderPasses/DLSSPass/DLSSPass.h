/***************************************************************************
 # Copyright (c) 2015-23, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY
 # EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 # PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 # OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 **************************************************************************/
#pragma once

#include "Falcor.h"
#include "RenderGraph/RenderPassHelpers.h"
#include "NGXWrapper.h"

using namespace Falcor;

class DLSSPass : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(DLSSPass, "DLSSPass", "DL antialiasing/upscaling.");

    /// The complete NVSDK_NGX_PerfQuality_Value set. SDK names, which differ from NVIDIA's UI names:
    /// MaxQuality = "Quality" (1/1.5), MaxPerf = "Performance" (1/2), UltraPerformance =
    /// "Ultra Performance" (1/3). UltraQuality (1/1.3) was specified but never shipped commercially.
    enum class Profile : uint32_t
    {
        MaxPerf,
        Balanced,
        MaxQuality,
        UltraPerformance,
        UltraQuality,
        DLAA,   ///< Native resolution, no upscaling -- required to use DLSS as a pure denoiser column.
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

    /// Super Resolution denoising network. NOTE these letters mean something DIFFERENT from the Ray
    /// Reconstruction presets of the same name -- they are separate enums in separate headers. Per
    /// nvsdk_ngx_defs.h (310.7.0): A..D removed, E/F deprecated, G..I and N/O "do not use", leaving
    /// J, K, L, M. K is the transformer model and the default for DLAA/Balanced/Quality; L is the
    /// default for Ultra Performance and M for Performance; J trades ghosting for flicker versus K.
    /// Which nvngx_dlss.dll -- and therefore which trained network family -- NGX loads.
    ///
    /// The preset LETTER alone does not identify a model: the same letter maps to a different network
    /// in different SDK generations. The architecture is chosen here, the variant within it by
    /// RenderPreset. Legacy is the only way to reach a convolutional model, because the 310.x line
    /// removed every CNN preset.
    enum class SDKVariant : uint32_t
    {
        Current,   ///< 310.7.0 (DLSS 4). Transformer. Presets J/K/L/M.
        LegacyCNN, ///< 3.7.20. Convolutional. Presets A..F. NOTE: no Ray Reconstruction in this line.
    };

    FALCOR_ENUM_INFO(
        SDKVariant,
        {
            {SDKVariant::Current, "Current"},
            {SDKVariant::LegacyCNN, "LegacyCNN"},
        }
    );

    /// Super Resolution network. Which of these are valid depends on SDKVariant -- an unimplemented
    /// preset silently reverts to the DLL's default rather than failing, so pairing them wrongly
    /// produces a plausible image of the wrong model. That is the whole trap this enum documents.
    ///
    ///   Current (310.7.0, transformer): J K L M   -- A..D removed, E/F deprecated, rest "do not use"
    ///   LegacyCNN (3.7.20, CNN):        A..F      -- J..O do not exist in that DLL
    enum class RenderPreset : uint32_t
    {
        Default,                  ///< Let NGX choose: K for DLAA/Balanced/Quality, M for Perf, L for Ultra Perf.
        A_CNN,                    ///< Legacy only. Stability-oriented CNN.
        B_CNN,                    ///< Legacy only. As A, tuned for Ultra Performance.
        C_CNN,                    ///< Legacy only. Favours responsiveness on fast motion.
        D_CNN,                    ///< Legacy only. The DLSS 2/3-era default CNN.
        E_CNN,                    ///< Legacy only.
        F_CNN,                    ///< Legacy only. Default for Ultra Performance / DLAA in 3.x.
        J_TransformerLessGhost,   ///< Like K, slightly less ghosting for slightly more flicker.
        K_TransformerBestQuality, ///< Best image quality, higher cost. Default for DLAA/Balanced/Quality.
        L_TransformerUltraPerf,   ///< Tuned for, and the default of, Ultra Performance.
        M_TransformerPerf,        ///< Tuned for, and the default of, Performance.
    };

    FALCOR_ENUM_INFO(
        RenderPreset,
        {
            {RenderPreset::Default, "Default"},
            {RenderPreset::A_CNN, "A_CNN"},
            {RenderPreset::B_CNN, "B_CNN"},
            {RenderPreset::C_CNN, "C_CNN"},
            {RenderPreset::D_CNN, "D_CNN"},
            {RenderPreset::E_CNN, "E_CNN"},
            {RenderPreset::F_CNN, "F_CNN"},
            {RenderPreset::J_TransformerLessGhost, "J_TransformerLessGhost"},
            {RenderPreset::K_TransformerBestQuality, "K_TransformerBestQuality"},
            {RenderPreset::L_TransformerUltraPerf, "L_TransformerUltraPerf"},
            {RenderPreset::M_TransformerPerf, "M_TransformerPerf"},
        }
    );

    enum class MotionVectorScale : uint32_t
    {
        Absolute, ///< Motion vectors are provided in absolute screen space length (pixels).
        Relative, ///< Motion vectors are provided in relative screen space length (pixels divided by screen width/height).
    };

    FALCOR_ENUM_INFO(
        MotionVectorScale,
        {
            {MotionVectorScale::Absolute, "Absolute"},
            {MotionVectorScale::Relative, "Relative"},
        }
    );

    static ref<DLSSPass> create(ref<Device> pDevice, const Properties& props) { return make_ref<DLSSPass>(pDevice, props); }

    DLSSPass(ref<Device> pDevice, const Properties& props);

    virtual Properties getProperties() const override;
    virtual RenderPassReflection reflect(const CompileData& compileData) override;
    virtual void setScene(RenderContext* pRenderContext, const ref<Scene>& pScene) override;
    virtual void execute(RenderContext* pRenderContext, const RenderData& renderData) override;
    virtual void renderUI(Gui::Widgets& widget) override;

private:
    void initializeDLSS(RenderContext* pRenderContext);
    void executeInternal(RenderContext* pRenderContext, const RenderData& renderData);

    // Options
    bool mEnabled = true;
    Profile mProfile = Profile::Balanced;
    RenderPreset mPreset = RenderPreset::Default;
    /// Only read when the NGX session is created. NVSDK_NGX_*_Init is per-device and per-process, so
    /// this cannot be flipped live once a session exists -- compare the two as separate runs.
    SDKVariant mSDKVariant = SDKVariant::Current;
    MotionVectorScale mMotionVectorScale = MotionVectorScale::Absolute;
    bool mIsHDR = true;
    float mSharpness = 0.f;
    float mExposure = 0.f;
    bool mExposureUpdated = true;

    bool mRecreate = true;
    uint2 mInputSize = {};      ///< Input size in pixels.
    uint2 mDLSSOutputSize = {}; ///< DLSS output size in pixels.
    uint2 mPassOutputSize = {}; ///< Pass output size in pixels. If different from DLSS output size, the image gets bilinearly resampled.
    RenderPassHelpers::IOSize mOutputSizeSelection = RenderPassHelpers::IOSize::Default; ///< Selected output size.

    ref<Scene> mpScene;
    ref<Texture> mpOutput;   ///< Internal output buffer. This is used if format/size conversion upon output is needed.
    ref<Texture> mpExposure; ///< Texture of size 1x1 holding exposure value.

    std::shared_ptr<NGXWrapper> mpNGXWrapper;   ///< Shared per-device NGX session, see NGXWrapper::acquire().
};

FALCOR_ENUM_REGISTER(DLSSPass::Profile);
FALCOR_ENUM_REGISTER(DLSSPass::RenderPreset);
FALCOR_ENUM_REGISTER(DLSSPass::SDKVariant);
FALCOR_ENUM_REGISTER(DLSSPass::MotionVectorScale);
