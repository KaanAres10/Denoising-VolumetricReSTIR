from falcor import *

gAccumulateParams = {
    "enableAccumulation": False
}

def render_graph():
    g = RenderGraph("Volumetric ReSTIR")
    loadRenderPassLibrary("AccumulatePass.dll")    
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")
    
    # Create Passes
    VolumetricReSTIR = createPass(
        'VolumetricReSTIR',
        {
            'mParams': VolumetricReSTIRParams(
                mUseSurfaceScene = True,
                mUseEmissiveLights = True,
                mUseEnvironmentLights = False,
                mTemporalReuseMThreshold = 10.0
            )
        }
    )
    AccumulatePass = createPass('AccumulatePass', gAccumulateParams)
    ToneMapper = createPass('ToneMapper', {
        'operator': ToneMapOp.Linear,
        'autoExposure': True,
        'exposureCompensation': 0.0,
        'clamp': True,
        'exposureValue': 0.0,
        'filmSpeed': 100.0,
        'whiteBalance': False,
        'whitePoint': 6500.0,
        'whiteMaxLuminance': 1.0,
        'whiteScale': 1.0,
        'fNumber': 1.0,
        'shutter': 1.0,
        'exposureMode': ExposureMode.AperturePriority,
    })

    # Add Passes
    g.addPass(VolumetricReSTIR, 'VolumetricReSTIR')
    g.addPass(AccumulatePass, 'AccumulatePass')
    g.addPass(ToneMapper, 'ToneMapper')

    # Connect Edges
    g.addEdge('VolumetricReSTIR.accumulated_color', 'AccumulatePass.input')
    g.addEdge('AccumulatePass.output', 'ToneMapper.src')
    
    # Mark the output for the global capture system
    g.markOutput('ToneMapper.dst') 
    
    return g
    
# Scene
m.loadScene("Bistro_5_1/BistroExterior.fbx")
m.scene.setEnvMap("skylight-morn.exr")
m.scene.setEnvMapRotation(float3(0,72.5,0))
m.scene.setEnvMapIntensity(0)

m.addGVDBVolume(
    sigma_a=float3(10,10,10),
    sigma_s=float3(80,80,80),
    g=0.0,
    dataFile="smoke-plume-2",
    numMips=4
)

m.scene.animated = False
m.scene.camera.animated = False
m.scene.camera.position = float3(-15.149291,8.352362,-8.399609)
m.scene.camera.target = float3(-14.742913,8.025879,-7.546224)
m.scene.camera.up = float3(0.004061,0.999961,0.007782)
m.scene.cameraSpeed = 1.0

# Setup Graph
graph = render_graph()
m.addGraph(graph)

# Window Configuration
m.resizeSwapChain(1920, 1080)
m.ui = True

# Time Settings
t.time = 0
t.framerate = 0
