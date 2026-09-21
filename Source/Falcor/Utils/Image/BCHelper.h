#pragma once
// BC4 (single-channel UNORM) block compression, ported verbatim from the Falcor 4.x fork
// (Source/Falcor/Utils/Image/BCHelper.{h,cpp}), which used it for the GVDB density atlas under
// ATLAS_COMPRESSION == 2. Derived from DirectXTex.
//
// The conservative variant rounds toward the endpoint that does not underestimate, so a
// conservative density grid compressed this way still bounds the true density from above -- which
// is what the ratio/residual trackers rely on.
#include "Core/Macros.h"
#include "Utils/Math/Vector.h"

#include <cstdint>
#include <cstring>
#include <vector>

namespace Falcor
{

#pragma warning(push)
#pragma warning(disable : 4201)
// BC4U/BC5U
struct BC4_UNORM
{
    float R(size_t uOffset) const noexcept
    {
        size_t uIndex = GetIndex(uOffset);
        return DecodeFromIndex(uIndex);
    }

    float DecodeFromIndex(size_t uIndex) const noexcept
    {
        if (uIndex == 0)
            return red_0 / 255.0f;
        if (uIndex == 1)
            return red_1 / 255.0f;
        float fred_0 = red_0 / 255.0f;
        float fred_1 = red_1 / 255.0f;
        if (red_0 > red_1)
        {
            uIndex -= 1;
            return (fred_0 * float(7u - uIndex) + fred_1 * float(uIndex)) / 7.0f;
        }
        else
        {
            if (uIndex == 6)
                return 0.0f;
            if (uIndex == 7)
                return 1.0f;
            uIndex -= 1;
            return (fred_0 * float(5u - uIndex) + fred_1 * float(uIndex)) / 5.0f;
        }
    }

    size_t GetIndex(size_t uOffset) const noexcept
    {
        return static_cast<size_t>((data >> (3 * uOffset + 16)) & 0x07);
    }

    void SetIndex(size_t uOffset, size_t uIndex) noexcept
    {
        data &= ~(uint64_t(0x07) << (3 * uOffset + 16));
        data |= (uint64_t(uIndex) << (3 * uOffset + 16));
    }

    union
    {
        struct
        {
            uint8_t red_0;
            uint8_t red_1;
            uint8_t indices[6];
        };
        uint64_t data;
    };
};
#pragma warning(pop)

// BC4 compression
class FALCOR_API BCHelper
{
public:
    /** Compress a single-channel float volume slice-by-slice into BC4_UNORM blocks.
        \param[in] data       Source, width*height*depth floats, row-major.
        \param[in] imgDim     (width, height, depth) in texels.
        \param[in] maxVal     Value mapped to 1.0; the shader multiplies back by this.
        \param[in] isConservative  Round so the result never underestimates (conservative grids).
        \param[out] compressedData  BC4 blocks for a texture of ceil(w/4)*4 x ceil(h/4)*4 x depth.
    */
    static void CompressImage(const float* data, int3 imgDim, float maxVal, bool isConservative, std::vector<uint8_t>& compressedData);
};

} // namespace Falcor
