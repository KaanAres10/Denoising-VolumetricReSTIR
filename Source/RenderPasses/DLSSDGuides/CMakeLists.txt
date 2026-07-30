add_plugin(DLSSDGuides)

target_sources(DLSSDGuides PRIVATE
    DLSSDGuides.cpp
    DLSSDGuides.h
    DLSSDGuides.cs.slang
)

target_copy_shaders(DLSSDGuides RenderPasses/DLSSDGuides)

target_source_group(DLSSDGuides "RenderPasses")
