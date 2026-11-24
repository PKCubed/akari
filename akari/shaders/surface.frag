// Pass 1: solid geometry.  Output = linear HDR colour (rgb) + hit distance (a).
// Stage, wall and fixtures are intersected analytically; only the person is
// raymarched, and only for rays that enter his bounding sphere.
uniform float uAmbient;
out vec4 fragColor;

const float FAR = 70.0;

// ---------------------------------------------------------------- person SDF
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
    vec3 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}
float smin(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}
vec2 opU(vec2 a, vec2 b) { return a.x < b.x ? a : b; }

// material ids: 1 deck, 2 wall, 3 trousers, 4 shirt, 5 skin, 7 house floor, 10+i fixture i
vec2 mapPerson(vec3 q) {
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
vec3 personNormal(vec3 q) {
    const vec2 e = vec2(1.0, -1.0) * 0.5773 * 0.002;
    return normalize(e.xyy * mapPerson(q + e.xyy).x + e.yyx * mapPerson(q + e.yyx).x +
                     e.yxy * mapPerson(q + e.yxy).x + e.xxx * mapPerson(q + e.xxx).x);
}

// ---------------------------------------------------------------- analytic hits
float boxHit(vec3 ro, vec3 rd, vec3 c, vec3 h, out vec3 n) {
    vec3 m = 1.0 / rd, o = ro - c, k = abs(m) * h;
    vec3 t1 = -m * o - k, t2 = -m * o + k;
    float tN = max(max(t1.x, t1.y), t1.z), tF = min(min(t2.x, t2.y), t2.z);
    if (tN > tF || tN < 0.0) return -1.0;
    n = -sign(rd) * step(t1.yzx, t1.xyz) * step(t1.zxy, t1.xyz);
    return tN;
}
float capHit(vec3 ro, vec3 rd, vec3 pa, vec3 pb, float ra) {
    vec3 ba = pb - pa, oa = ro - pa;
    float baba = dot(ba, ba), bard = dot(ba, rd), baoa = dot(ba, oa);
    float rdoa = dot(rd, oa), oaoa = dot(oa, oa);
    float a = baba - bard * bard, b = baba * rdoa - baoa * bard;
    float c = baba * oaoa - baoa * baoa - ra * ra * baba;
    float h = b * b - a * c;
    if (h >= 0.0) {
        float t = (-b - sqrt(h)) / a, y = baoa + t * bard;
        if (y > 0.0 && y < baba) return t;
        vec3 oc = (y <= 0.0) ? oa : ro - pb;
        b = dot(rd, oc); c = dot(oc, oc) - ra * ra; h = b * b - c;
        if (h > 0.0) return -b - sqrt(h);
    }
    return -1.0;
}
vec3 capNormal(vec3 p, vec3 a, vec3 b, float r) {
    vec3 ba = b - a, pa = p - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return (pa - h * ba) / r;
}
vec2 sphereHit(vec3 ro, vec3 rd, vec3 c, float r) {
    vec3 oc = ro - c;
    float b = dot(oc, rd), h = b * b - dot(oc, oc) + r * r;
    if (h < 0.0) return vec2(-1.0);
    h = sqrt(h);
    return vec2(-b - h, -b + h);
}

// ---------------------------------------------------------------- shadows
float shadowMarch(vec3 ro, vec3 rd, float tmax) {
    float res = 1.0, t = 0.03;
    for (int i = 0; i < 24; i++) {
        float h = mapPerson(ro + rd * t - uPerson).x;
        res = min(res, 10.0 * h / t);
        t += clamp(h, 0.03, 0.5);
        if (res < 0.002 || t > tmax) break;
    }
    return clamp(res, 0.0, 1.0);
}
float shadow(vec3 p, vec3 n, int i, vec3 L, float d) {
    // Only march when the light ray actually passes near the person.
    if (!nearPersonShadow(i, -L, d)) return 1.0;
    if (segSegDist(p, uLPos[i], personA(), personB()) > 0.45) return 1.0;
    return shadowMarch(p + n * 0.02, L, d);
}

// ---------------------------------------------------------------- shading
vec3 albedoOf(float m, vec3 p, vec3 n) {
    if (m < 1.5) {                                        // deck + spike-tape centre lines
        float tape = 1.0 - smoothstep(0.0, 0.02, min(abs(p.x), abs(p.z)));
        return mix(vec3(0.14, 0.135, 0.13), vec3(0.6), tape * step(0.5, n.y));
    }
    if (m < 2.5) return vec3(0.34, 0.34, 0.36);
    if (m < 3.5) return vec3(0.05, 0.07, 0.14);
    if (m < 4.5) return vec3(0.72, 0.72, 0.74);
    if (m < 5.5) return vec3(0.55, 0.38, 0.30);
    return vec3(0.05);
}

vec3 shade(vec3 p, vec3 n, float m) {
    if (m > 9.5) {                                        // fixture body with glowing lens
        int fi = int(m - 10.0 + 0.5);
        float face = dot(n, uLDir[fi]);
        return vec3(0.03) + uLCol[fi] * smoothstep(0.55, 0.9, face) * 4.0;
    }
    vec3 alb = albedoOf(m, p, n);
    vec3 col = alb * uAmbient;
    for (int k = 0; k < MAX_LIGHTS; k++) {
        if (k >= uNumActive) break;
        int i = uActive[k];
        vec3 Lv = uLPos[i] - p;
        float d2 = dot(Lv, Lv), id = inversesqrt(d2);
        vec3 L = Lv * id;
        float spot = smoothstep(uLCone[i].x, uLCone[i].y, dot(-L, uLDir[i]));
        float ndl = dot(n, L);
        if (spot <= 0.0 || ndl <= 0.0) continue;
        col += alb * uLCol[i] * (spot * ndl * (REF * REF) / (d2 + 6.0) * shadow(p, n, i, L, d2 * id));
    }
    return col;
}

void main() {
    vec3 ro = uCamPos, rd = camRay(gl_FragCoord.xy);
    float t = FAR, m = 0.0;
    vec3 n = vec3(0.0, 1.0, 0.0), nb;

    if (rd.y < 0.0) {                                     // house floor
        float tf = (-0.9 - ro.y) / rd.y;
        if (tf > 0.0 && tf < t) { t = tf; m = 7.0; n = vec3(0.0, 1.0, 0.0); }
    }
    float tb = boxHit(ro, rd, vec3(0.0, -0.45, -0.5), vec3(5.0, 0.45, 3.5), nb);   // deck
    if (tb > 0.0 && tb < t) { t = tb; m = 1.0; n = nb; }
    tb = boxHit(ro, rd, vec3(0.0, 3.6, -4.6), vec3(7.0, 4.7, 0.1), nb);             // back wall
    if (tb > 0.0 && tb < t) { t = tb; m = 2.0; n = nb; }

    for (int i = 0; i < MAX_LIGHTS; i++) {                // fixture bodies
        if (i >= uCount) break;
        vec3 a = uLPos[i], b = uLPos[i] - uLDir[i] * 0.28;
        vec3 oc = ro - (a + b) * 0.5;                       // bounding-sphere reject
        float bb = dot(oc, rd);
        if (bb * bb - dot(oc, oc) + 0.06 < 0.0) continue;
        float tc = capHit(ro, rd, a, b, 0.10);
        if (tc > 0.0 && tc < t) { t = tc; m = 10.0 + float(i); n = capNormal(ro + rd * tc, a, b, 0.10); }
    }

    vec2 bs = sphereHit(ro, rd, uPerson + vec3(0.0, 0.9, 0.0), 1.0);                // person
    if (bs.y > 0.0 && bs.x < t) {
        float tp = max(bs.x, 0.0), tEnd = min(bs.y, t);
        for (int i = 0; i < 64; i++) {
            vec2 h = mapPerson(ro + rd * tp - uPerson);
            if (h.x < 0.001) { t = tp; m = h.y; n = personNormal(ro + rd * tp - uPerson); break; }
            tp += h.x;
            if (tp > tEnd) break;
        }
    }

    vec3 col = m > 0.5 ? shade(ro + rd * t, n, m) : vec3(0.0);
    fragColor = vec4(col, t);
}
