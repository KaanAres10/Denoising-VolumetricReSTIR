"""Re-apply the NRD matrix-layout correction to the vendored shaders.

WHY THIS EXISTS AS A BUILD STEP
-------------------------------
`/external/nrd-4/` is gitignored (~10 MB of built binaries, fetched per
Source/RenderPasses/NRDPass/README.md), so an edit made directly in that tree is NOT in version
control and disappears the moment NRD is re-fetched or rebuilt. The correction below is not optional
polish -- without it RELAX rejects every reprojection and accumulates 0.05 frames of history against a
30-frame cap -- so it has to be reapplied on every build, the same way build_scripts/protoc_shim
restores the runtime DLLs.

WHAT IT CORRECTS
----------------
This integration recompiles NRD's HLSL through Slang instead of consuming the precompiled DXIL that
NRD ships (PipelineDesc::computeShaderDXIL, which NRDIntegration.hpp uses), and then memcpys NRD's raw
constant blob into a D3D12 CBV. Every float4x4 in those cbuffers ends up TRANSPOSED relative to what
NRD's C++ wrote. float4 constants are unaffected, and that asymmetry -- correct vectors, transposed
matrices -- is what broke RELAX's frustum basis. Measured on bistro:

    RotateVector(           gWorldToViewPrev , gPrevFrustumForward ).z = 0.7984
    RotateVector( transpose(gWorldToViewPrev), gPrevFrustumForward ).z = 0.9984   <- the correct 1.0

Neither SlangCompilerFlags::MatrixLayoutColumnMajor nor "#pragma pack_matrix" changes the packing --
both leave the denoised output byte-identical -- so the correction is applied at the declaration.

Each matrix constant is renamed to `<name>_raw` and `<name>` is redefined as `transpose( <name>_raw )`.
Renaming moves nothing in the buffer, so NRD's blob still lines up byte for byte; only the
interpretation changes, and no call site needs touching.

Defining NRD_RAW_MATRICES at compile time selects the untransposed read instead.

[Falcor 9.0] Which branch is CORRECT depends on whether NRDPass's MatrixLayoutColumnMajor flag
reaches the compiler, not on this script. Falcor 8.0 passed the matrix layout as a compiler option
that Slang ignores, so NRD's column-major data was read transposed and the transpose branch was the
fix. Falcor 9.0 sets the layout through the Slang session, where it takes effect, so the matrices
arrive correctly: NRDPass now defines NRD_RAW_MATRICES by default and the transpose branch is the
FAULT; NRD4_TRANSPOSE_MATRICES=1 selects it for an A/B. The generated header
comment below still calls the untransposed read "the old, broken behaviour" -- it is stamped once and
never rewritten (see the marker check), so trust NRDPass.cpp over it. The patch is still worth
applying: it keeps both reads available behind one define, which is what makes the A/B possible.

Idempotent: a header that already carries the marker is left alone, so this is safe to run on every
build. See Source/RenderPasses/NRDPass/STATE.md for the full derivation.
"""

import io
import os
import sys

MARKER = "NRD_RAW_MATRICES"

# header -> the shared-constants macro whose block holds the matrix declarations
TARGETS = {
    "RELAX_Config.hlsli": "#define RELAX_SHARED_CONSTANTS",
    "REBLUR_Config.hlsli": "#define REBLUR_SHARED_CONSTANTS",
    "SIGMA_Config.hlsli": "#define SIGMA_SHARED_CONSTANTS",
}


def patch(path, block_prefix):
    data = io.open(path, "rb").read().decode("utf-8")
    if MARKER in data:
        return "already patched"

    lines = data.split("\n")
    cr = "\r" if lines and lines[0].endswith("\r") else ""

    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(block_prefix))
    except StopIteration:
        # A future NRD version may rename or restructure the block. Fail loudly: silently skipping
        # would ship a denoiser whose temporal accumulation does not work, which is exactly the
        # failure this whole exercise was about.
        raise SystemExit("%s: could not find '%s' -- NRD's shader layout changed, see STATE.md"
                         % (os.path.basename(path), block_prefix))

    end = start
    while lines[end].rstrip().endswith("\\"):
        end += 1

    mats = []
    for i in range(start, end + 1):
        if "float4x4," in lines[i]:
            name = lines[i].split("float4x4,")[1].split(")")[0].strip()
            mats.append(name)
            lines[i] = lines[i].replace("float4x4, %s )" % name, "float4x4, %s_raw )" % name)
    if not mats:
        raise SystemExit("%s: no float4x4 constants found in the block" % os.path.basename(path))

    w = max(len(m) for m in mats)
    body = [
        "",
        "// Applied by build_scripts/patch_nrd_matrix_layout.py -- do not hand-edit, /external/nrd-4/",
        "// is gitignored and this is reapplied on every build. Every float4x4 in this cbuffer arrives",
        "// TRANSPOSED relative to what NRD's C++ wrote, because this integration recompiles NRD's HLSL",
        "// through Slang rather than using its precompiled DXIL. float4 constants are unaffected.",
        "// Define NRD_RAW_MATRICES to get the old, broken behaviour back for an A/B.",
        "#ifdef " + MARKER,
    ] + ["    #define %-*s %s_raw" % (w, m, m) for m in mats] + [
        "#else",
    ] + ["    #define %-*s transpose( %s_raw )" % (w, m, m) for m in mats] + [
        "#endif",
    ]
    lines[end + 1:end + 1] = [b + cr for b in body]
    io.open(path, "wb").write("\n".join(lines).encode("utf-8"))
    return "patched %d matrices" % len(mats)


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: patch_nrd_matrix_layout.py <path to nrd Shaders dir>")
    shaders = argv[1]
    if not os.path.isdir(shaders):
        # NRD is optional (FALCOR_USE_NRD4=OFF), so a missing tree is not an error.
        print("NRD shaders not present at %s, nothing to patch" % shaders)
        return 0
    for name, prefix in sorted(TARGETS.items()):
        p = os.path.join(shaders, name)
        if not os.path.isfile(p):
            print("  %-24s missing, skipped" % name)
            continue
        print("  %-24s %s" % (name, patch(p, prefix)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
