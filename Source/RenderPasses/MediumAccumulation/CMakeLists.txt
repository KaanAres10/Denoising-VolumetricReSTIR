add_plugin(MediumAccumulation)

target_sources(MediumAccumulation PRIVATE
    MediumAccumulation.cpp
    MediumAccumulation.h
    MediumAccumulation.cs.slang
)

target_copy_shaders(MediumAccumulation RenderPasses/MediumAccumulation)

target_source_group(MediumAccumulation "RenderPasses")
