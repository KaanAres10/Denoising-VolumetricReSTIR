add_plugin(NRDAdapter)

target_sources(NRDAdapter PRIVATE
    NRDAdapter.cpp
    NRDAdapter.h
    NRDAdapter.cs.slang
)

# The guide packing layout depends on which NRD SDK NRDPass is linked against -- the two disagree
# on what RGB10A2 means and neither validates it. This pass does not link NRD itself, so the choice
# has to be forwarded explicitly.
#
# FALCOR_HAS_NRD4 reaches here only via `set(... PARENT_SCOPE)` from external/CMakeLists.txt, so it
# depends on external/ being added before Source/. If that ordering ever changes the variable is
# simply empty, this pass quietly compiles the v3.1 packing against a v4 NRDPass, and the result is a
# smeared image with no build error. FALCOR_USE_NRD4 is a cache OPTION and therefore always visible,
# which makes the inconsistency detectable -- fail the configure instead.
if(FALCOR_USE_NRD4 AND NOT FALCOR_HAS_NRD4)
    message(FATAL_ERROR
        "NRDAdapter: FALCOR_USE_NRD4 is ON but FALCOR_HAS_NRD4 did not reach this scope, so the "
        "guide packing would silently use the v3.1 layout against a v4 NRDPass. Ensure external/ is "
        "added before Source/ in the top-level CMakeLists.")
endif()

if(FALCOR_HAS_NRD4)
    target_compile_definitions(NRDAdapter PRIVATE FALCOR_HAS_NRD4=1)
endif()

target_copy_shaders(NRDAdapter RenderPasses/NRDAdapter)

target_source_group(NRDAdapter "RenderPasses")
