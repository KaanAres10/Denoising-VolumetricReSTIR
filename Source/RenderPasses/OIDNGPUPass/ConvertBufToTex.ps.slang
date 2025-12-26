cbuffer GlobalCB { uint gStride; };

// FIX: Use float (scalar) buffer to avoid stride ambiguity
StructuredBuffer<float> gInBuf; 

float4 main(float2 texC : TEXCOORD, float4 posH : SV_Position) : SV_Target {
    uint2 pos = (uint2)posH.xy;
    
    // Calculate base index for 4 floats per pixel
    uint baseIndex = (pos.y * gStride + pos.x) * 4;

    // Manually reconstruct RGBA
    float r = gInBuf[baseIndex + 0];
    float g = gInBuf[baseIndex + 1];
    float b = gInBuf[baseIndex + 2];
    
    // OIDN doesn't denoise Alpha, so we can output 1.0 or read the 4th float
    // float a = gInBuf[baseIndex + 3]; 
    
    return float4(r, g, b, 1.0);
}