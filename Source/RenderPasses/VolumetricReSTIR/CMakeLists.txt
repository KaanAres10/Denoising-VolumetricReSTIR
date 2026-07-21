add_plugin(VolumetricReSTIR)

target_sources(VolumetricReSTIR PRIVATE
    VolumetricReSTIR.cpp
    VolumetricReSTIR.h
    Utils.cpp
    Utils.h
    HostDeviceSharedDefinitions.slangh

    ArrayDataProvider.slang
    ComputeInitialSample.slang
    CopyReservoirs.cs.slang
    FinalShading.cs.slang
    GenerateFeatures.cs.slang
    HostDeviceSharedConstants.slang
    InlineRayTracingHelpers.slang
    Reservoir.slang
    ReSTIRHelper.slang
    SpatialReuse.cs.slang
    TemporalReuse.cs.slang
    TraceRays.cs.slang
    VolumeBase.slang
    VolumePathTracingFunctions.slang
    VolumeTrackingAdapterGVDB.slang
    VolumeUtils.slang
)

target_copy_shaders(VolumetricReSTIR RenderPasses/VolumetricReSTIR)

target_source_group(VolumetricReSTIR "RenderPasses")
