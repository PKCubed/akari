// Pass 3 (window resolution): surfaces + depth-aware upsampled haze, tone-mapped.
uniform sampler2D uSurf;
uniform sampler2D uHazeTex;
uniform float uExposure;
out vec4 fragColor;

void main() {
    vec2 uv = gl_FragCoord.xy / uRes;
    vec4 s = texture(uSurf, uv);
    float dF = s.a;

    // Haze is lower resolution.  Where depth is smooth a plain bilinear fetch is
    // fine; only near depth edges (the actor's outline) do a joint-bilateral
    // upsample so beams don't bleed over the edge.
    vec4 hz = texture(uHazeTex, uv);
    vec3 haze = hz.rgb;
    if (abs(hz.a - dF) > 0.02 * dF + 0.03) {
        ivec2 hres = textureSize(uHazeTex, 0);
        vec2 hp = uv * vec2(hres) - 0.5;
        ivec2 i0 = ivec2(floor(hp));
        vec2 f = fract(hp);
        vec3 acc = vec3(0.0);
        float wsum = 0.0;
        for (int j = 0; j < 4; j++) {
            ivec2 o = ivec2(j & 1, j >> 1);
            vec4 h = texelFetch(uHazeTex, clamp(i0 + o, ivec2(0), hres - 1), 0);
            float wb = (o.x == 1 ? f.x : 1.0 - f.x) * (o.y == 1 ? f.y : 1.0 - f.y);
            float r = abs(h.a - dF) / (0.03 * dF + 0.05);
            float w = wb / (1.0 + r * r * r) + 1e-5 * wb;
            acc += h.rgb * w;
            wsum += w;
        }
        haze = acc / wsum;
    }
    vec3 col = s.rgb + haze;

    col = vec3(1.0) - exp(-col * uExposure);              // tone-map
    col = pow(col, vec3(1.0 / 2.2));
    col += (ign(gl_FragCoord.xy + 3.0) - 0.5) / 255.0;    // dither against banding
    fragColor = vec4(col, 1.0);
}
