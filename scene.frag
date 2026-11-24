#version 330 core
// Whole scene is one raymarched fragment shader:
//   * SDF stage + back wall + a person + fixture bodies
//   * every wash is a soft cone; haze is integrated along each view ray
#define MAX_LIGHTS 32
out vec4 fragColor;

uniform vec2  uRes;
uniform float uTime;
uniform vec3  uCamPos;
uniform vec3  uRight;
uniform vec3  uUp;
uniform vec3  uFwd;
uniform float uTanHalf;

uniform int   uCount;
uniform vec3  uLPos[MAX_LIGHTS];
uniform vec3  uLDir[MAX_LIGHTS];
uniform vec3  uLCol[MAX_LIGHTS];    // linear rgb * gain
uniform vec2  uLCone[MAX_LIGHTS];   // cos(outer), cos(inner)

uniform float uHaze;
uniform float uHazeG;
uniform vec3  uPerson;
uniform float uAmbient;
uniform float uExposure;
uniform int   uVolSteps;
uniform int   uHazeShadows;
uniform int   uFrame;

const float PI = 3.14159265;
const float REF = 6.0;                       // distance at which a light is "full"
const vec3 HAZE_MIN = vec3(-9.0, -0.9, -4.5);
const vec3 HAZE_MAX = vec3( 9.0,  8.0, 18.0);

// ---------------------------------------------------------------- noise
float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}
float vnoise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(mix(hash13(i), hash13(i + vec3(1,0,0)), f.x),
            mix(hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)), f.x), f.y),
        mix(mix(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)), f.x),
            mix(hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float ign(vec2 p) {                          // interleaved gradient noise
    return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
}

// ---------------------------------------------------------------- SDFs
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
    vec3 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}
float sdBox(vec3 p, vec3 b) {
    vec3 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}
float smin(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}
vec2 opU(vec2 a, vec2 b) { return a.x < b.x ? a : b; }

// material ids: 1 deck, 2 wall, 3 pants/shoes, 4 shirt, 5 skin, 7 house floor, 10+i fixture i
vec2 mapPerson(vec3 q) {
    float bound = length(q - vec3(0.0, 0.9, 0.0)) - 1.05;
    if (bound > 0.25) return vec2(bound, 3.0);          // cheap early-out
    vec3 m = vec3(abs(q.x), q.y, q.z);                  // mirror left/right
    float legs   = sdCapsule(m, vec3(0.10, 0.08, 0.0), vec3(0.11, 0.95, 0.0), 0.078);
    float shoes  = sdCapsule(m, vec3(0.10, 0.05, -0.02), vec3(0.10, 0.05, 0.13), 0.052);
    float torso  = sdCapsule(q, vec3(0.0, 1.00, 0.0), vec3(0.0, 1.38, 0.0), 0.165);
    float shldr  = sdCapsule(m, vec3(0.0, 1.40, 0.0), vec3(0.20, 1.40, 0.0), 0.075);
    float arms   = sdCapsule(m, vec3(0.22, 1.38, 0.0), vec3(0.25, 0.88, 0.04), 0.050);
    float shirt  = smin(torso, min(shldr, arms), 0.08);
    float hands  = length(m - vec3(0.255, 0.82, 0.05)) - 0.05;
    float neck   = sdCapsule(q, vec3(0.0, 1.42, 0.0), vec3(0.0, 1.55, 0.0), 0.05);
    float head   = length((q - vec3(0.0, 1.67, 0.01)) * vec3(1.0, 0.92, 1.0)) - 0.105;
    vec2 r = vec2(min(legs, shoes), 3.0);
    r = opU(r, vec2(shirt, 4.0));
    r = opU(r, vec2(min(min(hands, neck), head), 5.0));
    return r;
}

vec2 map(vec3 p) {
    vec2 r = vec2(sdBox(p - vec3(0.0, -0.45, -0.5), vec3(5.0, 0.45, 3.5)), 1.0);   // deck
    r = opU(r, vec2(p.y + 0.9, 7.0));                                               // house floor
    r = opU(r, vec2(sdBox(p - vec3(0.0, 3.6, -4.6), vec3(7.0, 4.7, 0.1)), 2.0));    // back wall
    r = opU(r, mapPerson(p - uPerson));
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= uCount) break;
        float d = sdCapsule(p, uLPos[i], uLPos[i] - uLDir[i] * 0.28, 0.10);
        r = opU(r, vec2(d, 10.0 + float(i)));
    }
    return r;
}

vec3 calcNormal(vec3 p) {
    const vec2 e = vec2(1.0, -1.0) * 0.5773 * 0.002;
    return normalize(e.xyy * map(p + e.xyy).x + e.yyx * map(p + e.yyx).x +
                     e.yxy * map(p + e.yxy).x + e.xxx * map(p + e.xxx).x);
}

// ---------------------------------------------------------------- shadows
float shadowPerson(vec3 ro, vec3 rd, float tmax) {       // soft shadow cast by the person
    float res = 1.0, t = 0.03;
    for (int i = 0; i < 28; i++) {
        float h = mapPerson(ro + rd * t - uPerson).x;
        res = min(res, 10.0 * h / t);
        t += clamp(h, 0.03, 0.5);
        if (res < 0.002 || t > tmax) break;
    }
    return clamp(res, 0.0, 1.0);
}

float segSegDist(vec3 p1, vec3 q1, vec3 p2, vec3 q2) {   // closest distance between segments
    vec3 d1 = q1 - p1, d2 = q2 - p2, r = p1 - p2;
    float a = dot(d1, d1), e = dot(d2, d2), f = dot(d2, r);
    float c = dot(d1, r), b = dot(d1, d2), den = a * e - b * b;
    float s = den > 1e-6 ? clamp((b * f - c * e) / den, 0.0, 1.0) : 0.0;
    float t = (b * s + f) / e;
    if (t < 0.0)      { t = 0.0; s = clamp(-c / a, 0.0, 1.0); }
    else if (t > 1.0) { t = 1.0; s = clamp((b - c) / a, 0.0, 1.0); }
    return length((p1 + d1 * s) - (p2 + d2 * t));
}
float personVisible(vec3 p, vec3 lp) {                   // cheap shadow for haze samples
    vec3 a = uPerson + vec3(0.0, 0.25, 0.0), b = uPerson + vec3(0.0, 1.55, 0.0);
    return smoothstep(0.12, 0.30, segSegDist(p, lp, a, b));
}

// ---------------------------------------------------------------- surfaces
vec3 albedoOf(float m, vec3 p, vec3 n) {
    if (m < 1.5) {                                        // deck, with spike tape on centre lines
        float tape = 1.0 - smoothstep(0.0, 0.02, min(abs(p.x), abs(p.z)));
        return mix(vec3(0.14, 0.135, 0.13), vec3(0.6), tape * step(0.5, n.y));
    }
    if (m < 2.5) return vec3(0.34, 0.34, 0.36);           // back wall
    if (m < 3.5) return vec3(0.05, 0.07, 0.14);           // trousers / shoes
    if (m < 4.5) return vec3(0.72, 0.72, 0.74);           // shirt
    if (m < 5.5) return vec3(0.55, 0.38, 0.30);           // skin
    return vec3(0.05);                                    // house floor
}

vec3 shade(vec3 p, vec3 n, float m) {
    if (m > 9.5) {                                        // fixture body with glowing lens
        int fi = int(m - 10.0 + 0.5);
        float face = dot(n, uLDir[fi]);
        return vec3(0.03) + uLCol[fi] * smoothstep(0.55, 0.9, face) * 4.0;
    }
    vec3 alb = albedoOf(m, p, n);
    vec3 col = alb * uAmbient;
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= uCount) break;
        vec3 lc = uLCol[i];
        if (lc.r + lc.g + lc.b < 0.002) continue;
        vec3 Lv = uLPos[i] - p;
        float d = length(Lv);
        vec3 L = Lv / d;
        float spot = smoothstep(uLCone[i].x, uLCone[i].y, dot(-L, uLDir[i]));
        if (spot <= 0.0) continue;
        float ndl = max(dot(n, L), 0.0);
        if (ndl <= 0.0) continue;
        float sh = shadowPerson(p + n * 0.02, L, d);
        col += alb * lc * spot * ndl * (REF * REF) / (d * d + 6.0) * sh;
    }
    return col;
}

// ---------------------------------------------------------------- haze
float hazeDensity(vec3 p) {
    vec3 q = p * vec3(0.30, 0.40, 0.30) + vec3(uTime * 0.05, uTime * 0.02, uTime * 0.03);
    float n = 0.6 * vnoise(q) + 0.4 * vnoise(q * 2.7 + 7.1);
    float settle = mix(1.25, 0.75, clamp(p.y / 8.0, 0.0, 1.0));   // a bit thicker low down
    return (0.45 + 1.1 * n) * settle;
}

vec3 scatter(vec3 ro, vec3 rd, float tEnd, vec2 frag) {
    if (uHaze <= 0.0001) return vec3(0.0);
    vec3 inv = 1.0 / rd;
    vec3 a = (HAZE_MIN - ro) * inv, b = (HAZE_MAX - ro) * inv;
    vec3 tmn = min(a, b), tmx = max(a, b);
    float tn = max(max(tmn.x, tmn.y), max(tmn.z, 0.0));
    float tf = min(min(tmx.x, tmx.y), min(tmx.z, tEnd));
    if (tf <= tn) return vec3(0.0);

    float dt = (tf - tn) / float(uVolSteps);
    float jit = ign(frag + 5.588238 * float(uFrame & 63));   // varies per frame; the eye averages it out
    vec3 acc = vec3(0.0);
    for (int s = 0; s < uVolSteps; s++) {
        vec3 p = ro + rd * (tn + (float(s) + jit) * dt);
        vec3 L = vec3(0.0);
        for (int i = 0; i < MAX_LIGHTS; i++) {
            if (i >= uCount) break;
            vec3 lc = uLCol[i];
            if (lc.r + lc.g + lc.b < 0.002) continue;
            vec3 v = p - uLPos[i];
            float d = length(v);
            vec3 vd = v / d;
            float spot = smoothstep(uLCone[i].x, uLCone[i].y, dot(vd, uLDir[i]));
            if (spot <= 0.0) continue;
            float cs = -dot(rd, vd);                         // 1 = looking straight into the light
            float ph = (1.0 - uHazeG * uHazeG) / pow(1.0 + uHazeG * uHazeG - 2.0 * uHazeG * cs, 1.5);
            float att = (REF * REF) / (d * d + 6.0);
            float vis = (uHazeShadows == 1) ? personVisible(p, uLPos[i]) : 1.0;
            L += lc * spot * att * ph * vis;
        }
        acc += L * (uHaze * hazeDensity(p)) * dt;
    }
    return acc;
}

// ---------------------------------------------------------------- main
void main() {
    vec2 frag = gl_FragCoord.xy;
    vec2 uv = (frag - 0.5 * uRes) / uRes.y;
    vec3 ro = uCamPos;
    vec3 rd = normalize(uFwd + (uRight * uv.x + uUp * uv.y) * 2.0 * uTanHalf);

    float t = 0.0;
    vec2 h = vec2(0.0);
    bool hit = false;
    for (int i = 0; i < 110; i++) {
        h = map(ro + rd * t);
        if (h.x < 0.0015 * t + 0.0005) { hit = true; break; }
        t += h.x;
        if (t > 70.0) break;
    }
    vec3 col = vec3(0.0);
    float tEnd = 70.0;
    if (hit) {
        vec3 p = ro + rd * t;
        col = shade(p, calcNormal(p), h.y);
        tEnd = t;
    }
    col += scatter(ro, rd, tEnd, frag);

    col = vec3(1.0) - exp(-col * uExposure);            // tone-map
    col = pow(col, vec3(1.0 / 2.2));
    col += (ign(frag + 3.0) - 0.5) / 255.0;             // dither against banding
    fragColor = vec4(col, 1.0);
}
