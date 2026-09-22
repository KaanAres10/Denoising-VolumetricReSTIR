/***************************************************************************
 # Motion-compensated temporal accumulation of the medium layer. See MediumAccumulation.h.
 #
 # The history holds the medium's radiance PER UNIT COVERAGE ("unpremultiplied", layer / coverage), and
 # the output multiplies back by this frame's exact coverage. The layer itself fades to zero across the
 # medium's thin rim and IS zero outside it, so resampling it -- which a moving camera does every frame,
 # between pixel centres -- mixed those zeros into the rim and eroded it from outside, frame after frame
 # (measured: the accumulated rim at 0.64 of its stopped value while moving, before RR ever saw it).
 # Per unit coverage the rim is as flat as the core, texels with no medium are left out of the fetch,
 # and the coverage profile itself is never resampled at all.
 **************************************************************************/

cbuffer CB
{
    uint2 gResolution;
    bool gHistoryValid;     // false on the first frame and after a resize
    bool gEnabled;          // false = pass the colour through untouched
    float gMaxFrames;
    float gDisocclusionRatio;
};

Texture2D<float4> gColor;           // the medium layer this frame (linear radiance)
Texture2D<float2> gMotionVec;       // current -> previous, normalised screen space (Falcor convention)
Texture2D<float> gCoverage;         // the medium's coverage, 1 - transmittance
Texture2D<float4> gPrevHistory;     // rgb = accumulated radiance PER UNIT COVERAGE, a = history length
Texture2D<float> gPrevCoverage;     // the coverage each history texel was accumulated under

RWTexture2D<float4> gOutput;
RWTexture2D<float4> gHistory;
RWTexture2D<float> gHistoryCoverage;

// Below this coverage a pixel has no medium to speak of: passed through, and not a history texel.
static const float kMinCoverage = 1e-3f;

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId: SV_DispatchThreadID)
{
    const uint2 pixel = dispatchThreadId.xy;
    if (any(pixel >= gResolution))
        return;

    const float3 color = gColor[pixel].rgb;
    const float coverage = saturate(gCoverage[pixel]);

    if (!gEnabled || coverage < kMinCoverage)
    {
        gOutput[pixel] = float4(color, 1.f);
        gHistory[pixel] = float4(0.f, 0.f, 0.f, 0.f);
        gHistoryCoverage[pixel] = coverage;
        return;
    }

    const float3 current = color / coverage;   // this frame's sample, per unit coverage
    float3 unpremul = current;
    float frames = 1.f;

    if (gHistoryValid)
    {
        const float2 prevPos = ((float2(pixel) + 0.5f) / float2(gResolution) + gMotionVec[pixel]) * float2(gResolution) - 0.5f;
        const int2 base = int2(floor(prevPos));
        const float2 f = prevPos - float2(base);
        const float w[4] = {(1.f - f.x) * (1.f - f.y), f.x * (1.f - f.y), (1.f - f.x) * f.y, f.x * f.y};
        const int2 offs[4] = {int2(0, 0), int2(1, 0), int2(0, 1), int2(1, 1)};

        // Bilinear fetch over the texels that HAD medium last frame. The plain-bilinear coverage (all
        // four texels) is kept for the disocclusion test: it says how much medium was there at all.
        float3 hist = 0.f;
        float histFrames = 0.f, wValid = 0.f, prevCoverage = 0.f, wAll = 0.f;
        [unroll]
        for (int k = 0; k < 4; k++)
        {
            const int2 t = base + offs[k];
            if (any(t < 0) || any(t >= int2(gResolution)))
                continue;
            const float c = gPrevCoverage[t];
            prevCoverage += w[k] * c;
            wAll += w[k];
            const float4 h = gPrevHistory[t];
            if (c >= kMinCoverage && h.a > 0.f)
            {
                hist += w[k] * h.rgb;
                histFrames += w[k] * h.a;
                wValid += w[k];
            }
        }

        // The same medium as last frame -- not medium the camera has just uncovered, which the
        // reprojection lands on a spot that had little or none -- and enough of it to trust.
        if (wAll > 0.f && wValid > 0.25f * wAll && prevCoverage / wAll >= gDisocclusionRatio * coverage)
        {
            hist /= wValid;
            histFrames /= wValid;
            frames = min(histFrames + 1.f, gMaxFrames);
            unpremul = lerp(hist, current, 1.f / frames);
        }
    }

    if (any(isnan(unpremul) || isinf(unpremul)))
    {
        unpremul = current;
        frames = 1.f;
    }

    gOutput[pixel] = float4(unpremul * coverage, 1.f);
    gHistory[pixel] = float4(unpremul, frames);
    gHistoryCoverage[pixel] = coverage;
}
