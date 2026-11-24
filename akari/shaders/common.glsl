#version 330 core
// Shared by every pass.  Prepended to each shader by viz.py.
#define MAX_LIGHTS 32

uniform vec2  uRes;          // resolution of the pass being drawn
uniform vec3  uCamPos;
uniform vec3  uRight;
uniform vec3  uUp;
uniform vec3  uFwd;
uniform float uTanHalf;

uniform int   uCount;                 // all fixtures (bodies are drawn even when dark)
uniform vec3  uLPos[MAX_LIGHTS];
uniform vec3  uLDir[MAX_LIGHTS];
uniform vec3  uLCol[MAX_LIGHTS];      // linear rgb * gain
uniform vec2  uLCone[MAX_LIGHTS];     // cos(outer), cos(inner)
uniform vec4  uLPers[MAX_LIGHTS];     // xyz: dir light->person, w: cos of person's angular radius
uniform float uLPersD[MAX_LIGHTS];    // distance light->person centre
uniform int   uNumActive;             // fixtures that are actually emitting
uniform int   uActive[MAX_LIGHTS];

uniform vec3  uPerson;
uniform int   uFrame;

const float REF = 6.0;                // distance at which a light is "full"

vec3 camRay(vec2 frag) {
    vec2 uv = (frag / uRes - 0.5) * vec2(uRes.x / uRes.y, 1.0);
    return normalize(uFwd + (uRight * uv.x + uUp * uv.y) * 2.0 * uTanHalf);
}

float ign(vec2 p) {                   // interleaved gradient noise
    return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
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

// The person's centre line, used for cheap shadow tests.
vec3 personA() { return uPerson + vec3(0.0, 0.08, 0.0); }
vec3 personB() { return uPerson + vec3(0.0, 1.70, 0.0); }

// True if a point in direction vd (unit, light -> point) at distance d from
// light i might be shadowed by the person.  Rejects almost every pixel for free.
bool nearPersonShadow(int i, vec3 vd, float d) {
    return dot(vd, uLPers[i].xyz) > uLPers[i].w && d > uLPersD[i] - 1.0;
}
