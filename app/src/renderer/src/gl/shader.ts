import { MAX_LIGHTS, MAX_SHADOW_STEPS, SHADING } from '@shared/lighting'

/**
 * The live-preview shader. backend/relight_backend/pipeline/shading.py computes
 * the same picture in Python; change both together and run `npm run parity`.
 *
 * Space: x = u, y = (1 - v) * aspect (up), z = depthScale * depth (toward the
 * viewer), all in image-width units. Colour math is in linear light.
 */

/** GLSL float literal (always with a decimal point). */
const f = (value: number): string => (Number.isInteger(value) ? `${value}.0` : `${value}`)

export const VERTEX_SHADER = /* glsl */ `#version 300 es
// One triangle that covers the screen. vUv is (0,0) at the top-left.
out vec2 vUv;
void main() {
  vec2 corner = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  vUv = vec2(corner.x, 1.0 - corner.y);
  gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
}
`

export const FRAGMENT_SHADER = /* glsl */ `#version 300 es
precision highp float;
precision highp int;

const int MAX_LIGHTS = ${MAX_LIGHTS};
const int MAX_SHADOW_STEPS = ${MAX_SHADOW_STEPS};
const int TYPE_POINT = 0;
const int TYPE_DIRECTIONAL = 1;
const int TYPE_SPOT = 2;
const int MODE_RELIT = 0;
const int MODE_ORIGINAL = 1;
const int MODE_LIGHT_ONLY = 2;

const float DEPTH_SCALE = ${f(SHADING.depthScale)};
const float WRAP_K = ${f(SHADING.wrapK)};
const float SPEC_FADE = ${f(SHADING.specFade)};
const float SHADOW_BIAS = ${f(SHADING.shadowBias)};
const float SHADOW_SOFT_MIN = ${f(SHADING.shadowSoftMin)};
const float SHADOW_SOFT_MAX = ${f(SHADING.shadowSoftMax)};
const float SHADOW_REACH = ${f(SHADING.shadowReach)};
const float SHADOW_THICKNESS = ${f(SHADING.shadowThickness)};
const float EMBED_FADE = ${f(SHADING.embedFade)};
const float RIM_STRENGTH = ${f(SHADING.rimStrength)};
const float RIM_WHITE = ${f(SHADING.rimWhite)};
const float RIM_THIN = ${f(SHADING.rimThin)};
const float RIM_BACK = ${f(SHADING.rimBack)};
const float RIM_FRONT_FADE = ${f(SHADING.rimFrontFade)};
const float FLATTEN_TARGET = ${f(SHADING.flattenTarget)};
const float FLATTEN_FLOOR = ${f(SHADING.flattenFloor)};
const float FLATTEN_MAX = ${f(SHADING.flattenMax)};
const float ALBEDO_FLOOR = ${f(SHADING.albedoFloor)};
const float SOFT_CLIP_START = ${f(SHADING.softClipStart)};

uniform sampler2D uAlbedo; // sRGB texture: sampling returns linear light
uniform sampler2D uNormal; // rgb = n * 0.5 + 0.5, camera space (+X right, +Y up, +Z to viewer)
uniform sampler2D uDepth;  // r: depth 0..1, 1 = nearest. g: highest depth within a few pixels.
uniform sampler2D uNormalSmooth; // the same normals, blurred
uniform sampler2D uAux;    // r: 1 where lights reach, 0 for sky. g: sqrt of large-scale brightness.
                           // b, a: the rim map, a vector pointing out of the shape a pixel is on;
                           // its length is 1 at the outline and 0 a band's width inside it
uniform float uAspect;     // image height / width

uniform int uLightCount;
uniform int uType[MAX_LIGHTS];
uniform vec3 uPosition[MAX_LIGHTS];
uniform vec3 uDirection[MAX_LIGHTS]; // unit vector the light travels along
uniform vec3 uColor[MAX_LIGHTS];     // linear RGB times intensity
uniform float uDiffusion[MAX_LIGHTS];
uniform float uRadius[MAX_LIGHTS];
uniform float uSpecular[MAX_LIGHTS];
uniform float uShininess[MAX_LIGHTS];
uniform vec2 uCone[MAX_LIGHTS];      // cos(outer edge), cos(inner edge)
uniform float uShadow[MAX_LIGHTS];   // shadow strength, 0 = no shadows
uniform float uEmbed[MAX_LIGHTS];    // how far the light is below the photo's surface at its own spot
                                     // (> 0 = behind it); directional: +-1000 by where it comes from

uniform float uSmoothing; // 0..1: lean the normals toward the blurred ones
uniform float uFlatten;   // 0..1: even out original light
uniform float uBase;      // keepOriginalLight + ambient
uniform float uGain;      // 2 ^ exposure
uniform int uShadowSteps;
uniform float uJitter;    // 0 = no jitter, 1 = one full step
uniform int uMode;
uniform float uSplit;     // < 0 = off; otherwise pixels left of this x show the original

in vec2 vUv;
out vec4 outColor;

vec3 linearToSrgb(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

// Identity up to SOFT_CLIP_START, then a smooth roll-off that never passes 1.
vec3 softClip(vec3 c) {
  float span = 1.0 - SOFT_CLIP_START;
  vec3 rolled = SOFT_CLIP_START + span * tanh((c - SOFT_CLIP_START) / span);
  return mix(c, rolled, step(SOFT_CLIP_START, c));
}

// Interleaved gradient noise in [0, 1).
float pixelNoise(vec2 fragCoord) {
  return fract(52.9829189 * fract(dot(fragCoord, vec2(0.06711056, 0.00583715))));
}

// How blocked this pixel is, 0..1: march toward the light over the depth heightfield.
//
// A light in front of the surface sees the photo's shapes as solids reaching all
// the way back. A light behind the surface must itself be in open space, so for
// it (behind = 1) shapes are shells of limited thickness and light can pass in
// the gap behind them.
float occlusion(vec3 position, vec3 ray, float diffusion, float jitter, float behind, float thickness) {
  float soft = mix(SHADOW_SOFT_MIN, SHADOW_SOFT_MAX, diffusion);
  float occluded = 0.0;
  for (int i = 0; i < MAX_SHADOW_STEPS; i++) {
    if (i >= uShadowSteps) break;
    float t = (float(i) + 0.5 + jitter) / float(uShadowSteps);
    vec3 point = position + ray * t;
    vec2 uv = vec2(point.x, 1.0 - point.y / uAspect);
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) continue;
    vec2 surface = DEPTH_SCALE * textureLod(uDepth, uv, 0.0).rg;
    float below = surface.r - point.z - SHADOW_BIAS; // how far under the surface the ray is here
    // Thickness is counted from the shape's top nearby, not from the steep wall
    // every outline has in a depth map; else a ray passing under a shape would
    // always hit that wall.
    float belowTop = surface.g - point.z - SHADOW_BIAS;
    float shell = 1.0 - clamp((belowTop - thickness) / (0.25 * thickness + 1e-4), 0.0, 1.0);
    occluded = max(occluded, clamp(below / soft, 0.0, 1.0) * mix(1.0, shell, behind));
  }
  return occluded;
}

vec3 contribution(int i, vec3 albedo, vec3 normal, vec3 position, vec2 rimVector, float noise) {
  vec3 toLight;
  vec3 ray;
  float attenuation = 1.0;

  if (uType[i] == TYPE_DIRECTIONAL) {
    toLight = -uDirection[i];
    ray = toLight * SHADOW_REACH;
  } else {
    ray = uPosition[i] - position;
    float dist = length(ray);
    toLight = ray / max(dist, 1e-5);
    float reach = dist / (uRadius[i] * (1.0 + uDiffusion[i]));
    attenuation = 1.0 / (1.0 + reach * reach);
  }
  if (uType[i] == TYPE_SPOT) {
    attenuation *= smoothstep(uCone[i].x, uCone[i].y, dot(-toLight, uDirection[i]));
  }

  float nDotL = dot(normal, toLight);
  float wrap = uDiffusion[i] * WRAP_K;
  float diffuse = clamp((nDotL + wrap) / (1.0 + wrap), 0.0, 1.0);

  vec3 halfVector = normalize(toLight + vec3(0.0, 0.0, 1.0));
  float specular = uSpecular[i] * pow(max(dot(normal, halfVector), 0.0), uShininess[i])
    * smoothstep(0.0, SPEC_FADE, nDotL);

  float shadow = 1.0;
  if (uShadow[i] > 0.0) {
    float behind = smoothstep(0.0, EMBED_FADE, uEmbed[i]);
    // Keep the shell above the light itself, or the light would be inside it.
    float thickness = min(SHADOW_THICKNESS, 0.7 * max(uEmbed[i], 0.0));
    shadow = 1.0 - uShadow[i]
      * occlusion(position, ray, uDiffusion[i], (noise - 0.5) * uJitter, behind, thickness);
  }

  // Rim light: an edge glows when it faces the light, or when the light is behind
  // the shape; not when the light is in front. It is not shadowed: the rim is
  // exactly the light that gets past the shape.
  float edge = length(rimVector);
  vec2 outward = rimVector / max(edge, 1e-4);
  // A light behind the shape rims every edge, also those turned away from it.
  float amount = clamp(max(dot(outward, toLight.xy), 0.0) + RIM_BACK * max(-toLight.z, 0.0), 0.0, 1.0)
    * (1.0 - smoothstep(0.0, RIM_FRONT_FADE, toLight.z));
  float reach = mix(RIM_THIN, 1.0, uDiffusion[i]); // a softer light, a broader rim
  float across = clamp((edge - (1.0 - reach)) / reach, 0.0, 1.0);
  float rim = RIM_STRENGTH * amount * across * across * across; // brightest at the very edge

  return uColor[i] * attenuation
    * (shadow * (albedo * diffuse + specular) + rim * mix(albedo, vec3(1.0), RIM_WHITE));
}

void main() {
  // Sample everything before branching: mip selection needs uniform control flow.
  vec3 albedo = texture(uAlbedo, vUv).rgb;
  vec3 normal = normalize(texture(uNormal, vUv).rgb * 2.0 - 1.0);
  vec3 smoothNormal = normalize(texture(uNormalSmooth, vUv).rgb * 2.0 - 1.0);
  vec4 aux = texture(uAux, vUv);
  float depth = texture(uDepth, vUv).r;
  vec2 rimVector = (aux.ba * 255.0 - 128.0) / 127.0; // stored as 128 + 127 * value

  bool showOriginal = uMode == MODE_ORIGINAL || (uSplit >= 0.0 && vUv.x < uSplit);
  if (showOriginal) {
    outColor = vec4(linearToSrgb(albedo), 1.0);
    return;
  }

  vec3 position = vec3(vUv.x, (1.0 - vUv.y) * uAspect, DEPTH_SCALE * depth);
  float noise = pixelNoise(gl_FragCoord.xy);

  normal = normalize(mix(normal, smoothNormal, uSmoothing));
  // What the lights fall on: the photo's colours, evened out toward mid exposure,
  // so new light does not just multiply the lighting already in the photo.
  float brightness = aux.g * aux.g;
  float even = min(pow(FLATTEN_TARGET / max(brightness, FLATTEN_FLOOR), uFlatten), FLATTEN_MAX);
  // Nothing is perfectly black under a light, so coloured light shows on dark backgrounds.
  vec3 litAlbedo = max(albedo * even, vec3(ALBEDO_FLOOR * uFlatten));

  vec3 lightSum = vec3(0.0);
  for (int i = 0; i < MAX_LIGHTS; i++) {
    if (i >= uLightCount) break;
    lightSum += contribution(i, litAlbedo, normal, position, rimVector, noise);
  }
  lightSum *= aux.r; // no light on the sky and the far distance

  vec3 color = uMode == MODE_LIGHT_ONLY ? lightSum : albedo * uBase + lightSum;
  outColor = vec4(linearToSrgb(softClip(color * uGain)), 1.0);
}
`
