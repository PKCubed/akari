// Pass 2 (reduced resolution): light scattered by haze along each view ray.
// For every lit fixture the ray is intersected with the beam cone, and samples
// are taken only inside that interval, so empty air costs nothing.
uniform sampler2D uSurf;              // pass 1: rgb + hit distance
uniform sampler3D uNoise;             // tileable haze density
uniform float uTime;
uniform float uHaze;
uniform float uHazeG;
uniform int   uSamples;               // samples per beam
uniform int   uHazeShadows;
out vec4 fragColor;

const vec3 HAZE_MIN = vec3(-9.0, -0.9, -4.5);
const vec3 HAZE_MAX = vec3( 9.0,  8.0, 18.0);

// Interval [t0, t1] where the ray is inside the forward cone (apex P, axis D,
// cos of half-angle c).  The forward cone is convex, so it is one interval.
bool coneInterval(vec3 ro, vec3 rd, vec3 P, vec3 D, float c, out float t0, out float t1) {
    vec3 co = ro - P;
    float rdD = dot(rd, D), coD = dot(co, D), c2 = c * c;
    float a = rdD * rdD - c2;
    if (abs(a) < 1e-5) a = 1e-5;                          // ray parallel to cone surface
    float b = rdD * coD - c2 * dot(rd, co);               // half of the usual b
    float k = coD * coD - c2 * dot(co, co);
    float h = b * b - a * k;
    if (a > 0.0) {                                        // ray direction lies inside the cone angle
        if (h < 0.0) { t0 = -1e9; t1 = 1e9; }             // (only happens for degenerate setups)
        else {
            float s = sqrt(h), r1 = (-b - s) / a, r2 = (-b + s) / a;
            if (rdD > 0.0) { t0 = r2; t1 = 1e9; } else { t0 = -1e9; t1 = r1; }
        }
    } else {                                              // ray crosses the cone sideways
        if (h < 0.0) return false;
        float s = sqrt(h), r1 = (-b + s) / a, r2 = (-b - s) / a;
        t0 = min(r1, r2); t1 = max(r1, r2);
        if (coD + 0.5 * (t0 + t1) * rdD < 0.0) return false;   // that's the mirror cone behind the light
    }
    return t1 > t0;
}

float density(vec3 p) {
    float n = texture(uNoise, p * 0.05 + vec3(uTime * 0.004, uTime * 0.0015, uTime * 0.003)).r;
    float settle = mix(1.25, 0.75, clamp(p.y / 8.0, 0.0, 1.0));    // a bit thicker low down
    return (0.3 + 1.4 * n) * settle;
}

void main() {
    vec2 uv = gl_FragCoord.xy / uRes;
    ivec2 sres = textureSize(uSurf, 0);
    float tEnd = texelFetch(uSurf, min(ivec2(uv * vec2(sres)), sres - 1), 0).a;
    vec3 ro = uCamPos, rd = camRay(gl_FragCoord.xy);

    vec3 acc = vec3(0.0);
    vec3 inv = 1.0 / rd;
    vec3 ta = (HAZE_MIN - ro) * inv, tb = (HAZE_MAX - ro) * inv;
    vec3 tmn = min(ta, tb), tmx = max(ta, tb);
    float tn = max(max(tmn.x, tmn.y), max(tmn.z, 0.0));
    float tf = min(min(tmx.x, tmx.y), min(tmx.z, tEnd));

    if (uHaze > 0.0001 && tf > tn) {
        float jit = ign(gl_FragCoord.xy + 5.588238 * float(uFrame & 63));
        float g = uHazeG, g2 = g * g;
        vec3 A = personA(), B = personB();
        for (int k = 0; k < MAX_LIGHTS; k++) {
            if (k >= uNumActive) break;
            int i = uActive[k];
            vec3 P = uLPos[i], D = uLDir[i];
            float t0, t1;
            if (!coneInterval(ro, rd, P, D, uLCone[i].x, t0, t1)) continue;
            t0 = max(t0, tn); t1 = min(t1, tf);
            if (t1 <= t0) continue;
            float dt = (t1 - t0) / float(uSamples);
            float sum = 0.0;
            for (int s = 0; s < uSamples; s++) {
                vec3 p = ro + rd * (t0 + (float(s) + jit) * dt);
                vec3 v = p - P;
                float d2 = dot(v, v);
                vec3 vd = v * inversesqrt(d2);
                float spot = smoothstep(uLCone[i].x, uLCone[i].y, dot(vd, D));
                float den = 1.0 + g2 + 2.0 * g * dot(rd, vd);          // Henyey-Greenstein
                float ph = (1.0 - g2) / (den * sqrt(den));
                float vis = 1.0;
                if (uHazeShadows == 1 && nearPersonShadow(i, vd, d2 * inversesqrt(d2)))
                    vis = smoothstep(0.12, 0.30, segSegDist(p, P, A, B));
                sum += spot * ph * vis * density(p) / (d2 + 6.0);
            }
            acc += uLCol[i] * (sum * dt * REF * REF);
        }
        acc *= uHaze;
    }
    fragColor = vec4(acc, tEnd);
}
