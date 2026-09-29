/* CogniDiff, procedural neural brain point cloud.
 *
 * Anatomically sculpted 3D human brain point cloud matching Image 2:
 * - Rounded cerebral dome with deep midline longitudinal fissure
 * - Voronoi cellular gyri producing plump, rounded, bulbous convolutions and sulci
 * - Dual-lobed cerebellum nestled below cerebrum with fine horizontal foliation striations
 * - Tapered brainstem with pons bulge
 * - 3D Directional Key Light + Frontal Camera Fill + Fresnel Rim Glow
 * - 100% VISIBLE MATTE BLUE: deep navy shadow, royal blue mid, and luminous sky-blue crests
 * - ZERO white blowout, zero glare, zero shine
 * - ZERO rotation: locked steady in clean, iconic front-top anatomical view
 * - NormalBlending: crisp, solid, beautiful 3D volume
 *
 * Exposes window.NeuralBrain.
 */

(function (global) {
  'use strict';

  // ---------------------------------------------------------------------
  // Deterministic RNG (Mulberry32)
  // ---------------------------------------------------------------------

  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function randomDirection(rand) {
    const u = rand() * 2 - 1;
    const phi = rand() * Math.PI * 2;
    const s = Math.sqrt(Math.max(0, 1 - u * u));
    return [s * Math.cos(phi), u, s * Math.sin(phi)];
  }

  // ---------------------------------------------------------------------
  // Anatomical Gyral Centers (Covering all lobes per hemisphere)
  // ---------------------------------------------------------------------

  const HEMI_SEEDS = [
    // Superior sagittal row (along midline fissure)
    [0.16, 0.80, 0.20],
    [0.17, 0.78, -0.15],
    [0.15, 0.68, 0.48],
    [0.16, 0.65, -0.45],
    [0.14, 0.50, 0.68],
    [0.14, 0.46, -0.68],
    [0.12, 0.25, 0.78],
    [0.12, 0.20, -0.78],

    // Frontal & Parietal dorsal (rich gyri on top and front face)
    [0.36, 0.72, 0.22],
    [0.38, 0.70, -0.16],
    [0.34, 0.58, 0.50],
    [0.36, 0.54, -0.50],
    [0.32, 0.38, 0.68],
    [0.32, 0.32, -0.68],
    [0.30, 0.16, 0.75],
    [0.30, 0.10, -0.75],

    // Lateral crown / Precentral & Postcentral gyri
    [0.58, 0.55, 0.18],
    [0.60, 0.52, -0.20],
    [0.54, 0.42, 0.48],
    [0.56, 0.38, -0.50],
    [0.50, 0.22, 0.62],
    [0.50, 0.16, -0.62],

    // Superior & Middle Temporal gyri (horizontal tiers matching Image 2 lateral profile)
    [0.68, 0.06, 0.32],
    [0.70, 0.08, 0.05],
    [0.68, 0.10, -0.22],
    [0.65, -0.10, 0.36],
    [0.66, -0.08, 0.12],
    [0.64, -0.06, -0.18],
    [0.56, -0.22, 0.28],
    [0.58, -0.20, 0.02],
    [0.54, -0.18, -0.28],

    // Occipital pole
    [0.38, 0.18, -0.76],
    [0.45, 0.06, -0.72],
    [0.22, -0.02, -0.78],
  ];

  // Pre-build symmetric gyri seed array
  const ALL_SEEDS = [];
  for (let s = 0; s < HEMI_SEEDS.length; s++) {
    const pt = HEMI_SEEDS[s];
    ALL_SEEDS.push([pt[0], pt[1], pt[2]]);
    ALL_SEEDS.push([-pt[0], pt[1], pt[2]]); // mirrored hemisphere
  }

  // Flattened for cache-friendly fast distance checks in JS loop
  const SEED_COORDS = new Float32Array(ALL_SEEDS.length * 3);
  for (let s = 0; s < ALL_SEEDS.length; s++) {
    SEED_COORDS[s * 3]     = ALL_SEEDS[s][0];
    SEED_COORDS[s * 3 + 1] = ALL_SEEDS[s][1];
    SEED_COORDS[s * 3 + 2] = ALL_SEEDS[s][2];
  }
  const NUM_SEEDS = ALL_SEEDS.length;

  // ---------------------------------------------------------------------
  // Full Brain Point Cloud Construction
  // ---------------------------------------------------------------------

  function buildBrain(count, seed) {
    const rand = mulberry32(seed);

    const nCortex = Math.floor(count * 0.77);
    const nCerebellum = Math.floor(count * 0.17);
    const nStem = count - nCortex - nCerebellum;

    const pos = new Float32Array(count * 3);
    const scatter = new Float32Array(count * 3);
    const size = new Float32Array(count);
    const alpha = new Float32Array(count);
    const region = new Float32Array(count);
    const seedAttr = new Float32Array(count);
    const normal = new Float32Array(count * 3);
    const elev = new Float32Array(count);

    let i = 0;
    const push = (x, y, z, s, a, reg, nx = 0, ny = 0, nz = 0, el = 0.5) => {
      pos[i * 3]     = x;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = z;
      size[i]        = s;
      alpha[i]       = a;
      region[i]      = reg;
      seedAttr[i]    = rand();
      normal[i * 3]     = nx;
      normal[i * 3 + 1] = ny;
      normal[i * 3 + 2] = nz;
      elev[i]        = el;

      const d = randomDirection(rand);
      const spread = 2.0 + Math.pow(rand(), 0.65) * 2.8;
      scatter[i * 3]     = d[0] * spread * 1.35;
      scatter[i * 3 + 1] = d[1] * spread * 0.90;
      scatter[i * 3 + 2] = d[2] * spread * 1.10;
      i++;
    };

    // 1. Cerebral Cortex (Anatomical lateral profile matching Image 2)
    const cellR = 0.24;

    for (let k = 0; k < nCortex; k++) {
      // Stratified spherical sampling
      const th = Math.acos(-0.75 + rand() * (0.98 - (-0.75)));
      const ph = -Math.PI + rand() * (Math.PI * 2.0);

      const y0 = Math.cos(th);
      const z0 = Math.sin(th) * Math.cos(ph);
      const x0 = Math.sin(th) * Math.sin(ph);

      // Anatomical dimensions: front-to-back elongated (Z), lateral width (X), vertical (Y)
      let bx = x0 * 0.70;
      let by = y0 * 0.65 + 0.18;
      let bz = z0 * 0.95;

      // A. Midline Longitudinal fissure cleft
      const fissure = 0.22 * Math.exp(-Math.pow(bx / 0.08, 2)) * Math.min(1.2, Math.max(0.2, (by + 0.10) / 0.70));
      const bxSign = bx >= 0 ? 1.0 : -1.0;
      bx -= bxSign * fissure * 0.25;

      // B. Parietal dome apex contour
      by += 0.08 * Math.exp(-Math.pow((bz + 0.10) / 0.50, 2)) * Math.max(0.0, by - 0.20);

      // C. Frontal lobe curvature & orbital undercut
      const orbit = Math.max(0.0, 0.12 - by) * Math.max(0.0, (bz - 0.25) / 0.60) * 0.45;
      by += orbit * 0.55;
      bz -= orbit * 0.20;

      // D. Sub-occipital shelf (cerebellar tentorium recess where cerebellum nests)
      const shelfZ = Math.max(0.0, -bz - 0.15);
      const shelfY = Math.max(0.0, 0.10 - by);
      const shelf = shelfZ * shelfY * 1.30;
      by += shelf * 0.60;
      bz += shelf * 0.35;

      // E. Sylvian fissure (Lateral sulcus) cleft
      const sylvLine = 0.06 - 0.28 * (bz - 0.10);
      const dSylv = Math.abs(by - sylvLine);
      const lat = Math.min(1.0, Math.max(0.0, (Math.abs(bx) - 0.25) / 0.35));
      const zAct = Math.exp(-Math.pow((bz - 0.12) / 0.35, 2));
      const sylv = Math.exp(-Math.pow(dSylv / 0.065, 2)) * lat * zAct * 0.14;
      bx -= bxSign * sylv * 0.38;

      // F. Temporal lobe forward thumb
      const tx = (Math.abs(bx) - 0.58) / 0.22;
      const ty = (by + 0.14) / 0.16;
      const tz = (bz - 0.24) / 0.28;
      const tDist = Math.sqrt(tx * tx + ty * ty + tz * tz);
      if (tDist < 1.0) {
        const tBulge = Math.pow(Math.cos(tDist * (Math.PI * 0.5)), 2) * 0.14;
        bx += bxSign * tBulge * 0.35;
        bz += tBulge * 0.18;
        by -= tBulge * 0.06;
      }

      // Voronoi distances d1 (closest) and d2 (2nd closest) to gyral seeds
      let min1 = 999.0;
      let min2 = 999.0;
      for (let sIdx = 0; sIdx < NUM_SEEDS; sIdx++) {
        const sx = SEED_COORDS[sIdx * 3];
        const sy = SEED_COORDS[sIdx * 3 + 1];
        const sz = SEED_COORDS[sIdx * 3 + 2];
        const dxx = bx - sx;
        const dyy = by - sy;
        const dzz = bz - sz;
        const distSq = dxx * dxx + dyy * dyy + dzz * dzz;
        if (distSq < min1) {
          min2 = min1;
          min1 = distSq;
        } else if (distSq < min2) {
          min2 = distSq;
        }
      }
      const d1 = Math.sqrt(min1);
      const d2 = Math.sqrt(min2);

      // Pillow crest (rounded cushion)
      const crestRatio = Math.min(1.0, d1 / cellR);
      const crest = Math.pow(Math.cos(crestRatio * (Math.PI / 2.0)), 2);
      // Sulcus groove (clean narrow ravine)
      const sulcus = Math.tanh((d2 - d1) / 0.045);
      const gyriElev = crest * (0.35 + 0.65 * sulcus);

      // Normal direction from center of closest hemisphere
      const hemiCx = bx >= 0 ? 0.18 : -0.18;
      let dirX = bx - hemiCx;
      let dirY = by - 0.10;
      let dirZ = bz;
      const dirLen = Math.sqrt(dirX * dirX + dirY * dirY + dirZ * dirZ + 1e-6);
      dirX /= dirLen; dirY /= dirLen; dirZ /= dirLen;

      // Gentle surface gyri displacement so outer cranial silhouette remains smooth matching reference video
      const moundDisp = (gyriElev - 0.40) * 0.045;
      const micro = Math.sin(bx * 26.0) * Math.sin(by * 26.0) * Math.sin(bz * 26.0) * 0.003;

      let px = bx + dirX * (moundDisp + micro);
      let py = by + dirY * (moundDisp + micro);
      let pz = bz + dirZ * (moundDisp + micro);

      // Volumetric mantle thickness
      const depth = Math.pow(rand(), 2.2) * 0.065;
      px -= dirX * depth;
      py -= dirY * depth;
      pz -= dirZ * depth;

      // Surface normal
      let nx = dirX + (rand() - 0.5) * 0.04;
      let ny = dirY + (rand() - 0.5) * 0.04;
      let nz = dirZ;
      const nLen = Math.sqrt(nx * nx + ny * ny + nz * nz + 1e-6);
      nx /= nLen; ny /= nLen; nz /= nLen;

      const al = Math.min(0.95, Math.max(0.22, 0.38 + 0.58 * gyriElev - depth * 3.5));
      const sz = 0.40 + 0.24 * gyriElev + rand() * 0.20;

      push(px, py, pz, sz, al, 0, nx, ny, nz, gyriElev);
    }

    // 2. Cerebellum (Snug in sub-occipital shelf at posterior-inferior)
    const nCbHalf = Math.floor(nCerebellum / 2);
    for (const sign of [-1.0, 1.0]) {
      const cx = sign * 0.21;
      const cy = -0.22;
      const cz = -0.42; // nestled right below occipital pole
      const rx = 0.23, ry = 0.17, rz = 0.25;

      for (let k = 0; k < nCbHalf; k++) {
        const u = -0.95 + rand() * 1.90;
        const phi = rand() * Math.PI * 2;
        const s = Math.sqrt(Math.max(0, 1.0 - u * u));

        const dx = s * Math.sin(phi);
        const dy = u;
        const dz = s * Math.cos(phi);

        // Fine horizontal folia striations
        const folia = Math.sin((cy + dy * ry) * 82.0);
        const rad = 1.0 + folia * 0.038;

        let cpx = cx + dx * rx * rad;
        let cpy = cy + dy * ry * rad;
        let cpz = cz + dz * rz * rad;

        const depthCb = Math.pow(rand(), 2.0) * 0.05;
        cpx -= dx * depthCb;
        cpy -= dy * depthCb;
        cpz -= dz * depthCb;

        const normFolia = Math.min(1.0, Math.max(0.0, (folia + 1.0) * 0.5));
        const al = Math.min(0.90, Math.max(0.22, 0.35 + 0.50 * normFolia));
        const sz = 0.36 + rand() * 0.20;

        push(cpx, cpy, cpz, sz, al, 2, dx, dy, dz, normFolia);
      }
    }

    // 3. Brainstem (Tapered pillar anterior to cerebellum with pons bulge, angled forward)
    for (let k = 0; k < nStem; k++) {
      const t = rand();
      const pons = 0.042 * Math.exp(-Math.pow(t - 0.22, 2) / 0.018);
      const radStem = (0.095 - 0.030 * t + pons) * Math.sqrt(0.20 + rand() * 0.80);
      const ang = rand() * Math.PI * 2;

      const sx = Math.cos(ang) * radStem;
      const sy = -0.18 - t * 0.46;
      // Angled forward toward +Z as it descends, matching lateral anatomy
      const sz = -0.10 + t * 0.10 + Math.sin(ang) * radStem * 0.75;

      const al = 0.35 + rand() * 0.35;
      const ptSize = 0.36 + rand() * 0.20;
      const snx = Math.cos(ang);
      const sny = 0.0;
      const snz = Math.sin(ang);

      push(sx, sy, sz, ptSize, al, 3, snx, sny, snz, 0.55);
    }

    return { pos, scatter, size, alpha, region, seed: seedAttr, normal, elev, count };
  }

  // ---------------------------------------------------------------------
  // Constellation link lines
  // ---------------------------------------------------------------------

  function buildNetworkLines(scatter, count, maxLines, seed) {
    const rand = mulberry32(seed ^ 0x51ed270b);
    const nodes = [];
    const stride = Math.max(1, Math.floor(count / 280));
    for (let i = 0; i < count; i += stride) {
      nodes.push([scatter[i * 3], scatter[i * 3 + 1], scatter[i * 3 + 2]]);
    }

    const verts = [];
    for (let a = 0; a < nodes.length && verts.length / 6 < maxLines; a++) {
      const dists = [];
      for (let b = 0; b < nodes.length; b++) {
        if (a === b) continue;
        const dx = nodes[a][0] - nodes[b][0];
        const dy = nodes[a][1] - nodes[b][1];
        const dz = nodes[a][2] - nodes[b][2];
        dists.push([dx * dx + dy * dy + dz * dz, b]);
      }
      dists.sort((p, q) => p[0] - q[0]);
      const links = 1 + Math.floor(rand() * 2);
      for (let n = 0; n < links && n < dists.length; n++) {
        const b = dists[n][1];
        if (dists[n][0] > 6.0) continue;
        verts.push(...nodes[a], ...nodes[b]);
      }
    }
    return new Float32Array(verts);
  }

  // ---------------------------------------------------------------------
  // Shaders (Sculpted 3D Directional Lighting, Visible Matte Blue)
  // ---------------------------------------------------------------------

  const VERTEX = `
    attribute vec3  aScatter;
    attribute vec3  aNormal;
    attribute float aElev;
    attribute float aSize;
    attribute float aAlpha;
    attribute float aRegion;
    attribute float aSeed;

    uniform float uTime;
    uniform float uMorph;
    uniform float uPulse;
    uniform vec3  uFocus;
    uniform float uFocusRadius;
    uniform vec2  uCursor;
    uniform float uCursorOn;
    uniform vec2  uAspect;
    uniform float uPixelRatio;
    uniform float uScale;

    varying float vAlpha;
    varying float vHeat;
    varying float vIllum;
    varying float vLit;
    varying float vMorph;

    void main() {
      // Subtle organic idle breathing
      vec3 drift = vec3(
        sin(uTime * 0.35 + aSeed * 21.0),
        cos(uTime * 0.29 + aSeed * 17.0),
        sin(uTime * 0.31 + aSeed * 13.0)
      ) * 0.003;

      float stagger = clamp(uMorph * 1.6 - aSeed * 0.6, 0.0, 1.0);
      float m = stagger * stagger * (3.0 - 2.0 * stagger);
      vec3 p = mix(position + drift, aScatter, m);

      float heat = 0.0;

      if (uPulse >= 0.0) {
        float axis = (position.z + 1.2) / 2.4;
        float band = abs(axis - uPulse);
        heat = max(heat, smoothstep(0.18, 0.02, band) * 0.85 * (1.0 - m));
      }

      if (uFocusRadius > 0.0) {
        float d = distance(position, uFocus);
        heat = max(heat, smoothstep(uFocusRadius, uFocusRadius * 0.25, d) * (1.0 - m));
      }

      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_Position = projectionMatrix * mv;

      // 3D Directional Key Light + Frontal Camera Fill + Fresnel Rim
      vec3 camNormal = normalize(normalMatrix * aNormal);
      vec3 lightDir = normalize(vec3(0.22, 0.85, 0.52));
      float diffuse = max(0.0, dot(camNormal, lightDir));
      float camFill = max(0.0, camNormal.z); // frontal fill lights the gyri on the face
      float rim = pow(clamp(1.0 - abs(camNormal.z), 0.0, 1.0), 1.45);

      // Very slight synaptic sparkle glow on selected particles (~16% of points)
      float sparkle = pow(aSeed, 4.0) * (0.80 + 0.20 * sin(uTime * 1.6 + aSeed * 25.0));

      // Balanced illumination with edge separation so brain never merges into background:
      float brainIllum = 0.30 + 0.34 * diffuse + 0.26 * camFill + 0.72 * rim + 0.35 * aElev + 0.34 * sparkle;

      // Localized small radius shine strictly on particles under cursor
      float lit = 0.0;
      if (uCursorOn > 0.5 && gl_Position.w > 0.0) {
        vec2 ndc = gl_Position.xy / gl_Position.w;
        float d = length((ndc - uCursor) * uAspect);
        lit = smoothstep(0.12, 0.0, d);
      }

      // --- Morph / Scatter state (Section 3): few randomly scattered particles survive ---
      // Survivors are a tiny random subset (~0.62% of points -> ~180-200 visible in viewport)
      float isSurvivor = step(aSeed, 0.0062);
      float subSeed = aSeed / 0.0062;

      // Three tiers of scattered particles:
      // 1) subSeed < 0.52: faded (soft, quiet shadow/mid blue, smaller pinpoint)
      // 2) subSeed 0.52..0.82: slight glow (medium alpha, royal blue with soft sheen)
      // 3) subSeed >= 0.82: more glow (high alpha, luminous sky-blue crest with breathing twinkle)
      float targetAlpha = 0.24;
      float targetIllum = 0.32;
      float targetSize = 0.82;

      if (subSeed >= 0.52 && subSeed < 0.82) {
        targetAlpha = 0.62;
        targetIllum = 0.70 + 0.14 * sin(uTime * 1.8 + aSeed * 45.0);
        targetSize = 1.15;
      } else if (subSeed >= 0.82) {
        targetAlpha = 0.96;
        targetIllum = 1.12 + 0.26 * sin(uTime * 2.4 + aSeed * 65.0);
        targetSize = 1.55;
      }

      float scatterAlpha = isSurvivor * targetAlpha;
      float brainAlpha = mix(aAlpha, 1.0, max(lit * 0.92, heat * 0.96));

      vAlpha = mix(brainAlpha, scatterAlpha, m);
      vIllum = mix(brainIllum, targetIllum, m);
      vLit = lit;
      vHeat = heat;
      vMorph = m;

      // Particles under cursor and focus beacon expand into radiant glowing points
      float sizeMult = mix(1.0, targetSize, m);
      float s = aSize * uScale * (1.0 + lit * 0.85 + heat * 1.40) * sizeMult;
      float maxPt = mix(mix(4.8, 6.8, lit), 7.2, heat);
      gl_PointSize = clamp(s * uPixelRatio * (15.5 / max(-mv.z, 0.1)), 1.5, maxPt);
    }
  `;

  const FRAGMENT = `
    precision mediump float;

    uniform vec3 uColorDark;    // rich navy shadow (#072464)
    uniform vec3 uColorMid;     // visible royal blue  (#1d64f2)
    uniform vec3 uColorLit;     // luminous cyan crest (#50c4ff)
    uniform float uOpacity;

    varying float vAlpha;
    varying float vHeat;
    varying float vIllum;
    varying float vLit;
    varying float vMorph;

    void main() {
      if (vAlpha < 0.002) discard;

      vec2 c = gl_PointCoord - vec2(0.5);
      float d = dot(c, c);
      if (d > 0.25) discard;

      // Crisp core with radiant bloom halo on particles under cursor
      float core = smoothstep(0.25, 0.04, d);
      float halo = smoothstep(0.25, 0.00, d) * mix(0.24, 0.72, vLit);
      float falloff = max(core, halo);

      // 3D sculpted visible blue (EXACT SAME PALETTE & SHADING IN BRAIN FORM):
      // Sulcal valleys & crevices: rich shadow navy blue
      // Gyri slopes & mid-body:     vivid royal blue
      // Gyri crests & rim highlights: luminous sky/cyan blue
      float t = clamp(vIllum, 0.0, 1.0);
      vec3 col;
      if (t < 0.50) {
        col = mix(uColorDark, uColorMid, t / 0.50);
      } else {
        col = mix(uColorMid, uColorLit, (t - 0.50) / 0.50);
      }

      // Very slight glow on elevated crests, sparkle particles, and glowing scattered particles
      float crestGlow = smoothstep(0.70, 1.0, vIllum);
      col += vec3(0.12, 0.38, 0.62) * (crestGlow * 0.40);

      // Radiant cursor glow: particles under cursor illuminate with vibrant electric cyan bloom
      if (vLit > 0.005) {
        vec3 glowCore = vec3(0.24, 0.82, 1.0);
        float glowInt = pow(vLit, 1.30) * 1.25;
        vec3 emissive = vec3(0.12, 0.48, 0.85) * glowInt;
        col = mix(col, glowCore, vLit * 0.85) + emissive;
        col = min(col, vec3(0.48, 0.94, 1.0));
      }

      // Visual cortex / regional focus highlight bloom (V1)
      if (vHeat > 0.005) {
        vec3 heatCore = vec3(0.55, 0.95, 1.0); // radiant cyan/white core
        vec3 heatEmissive = vec3(0.18, 0.65, 1.0) * pow(vHeat, 1.2) * 1.5;
        col = mix(col, heatCore, vHeat * 0.82) + heatEmissive;
        col = min(col, vec3(0.68, 0.98, 1.0));
      }

      float brainA = clamp(mix(vAlpha * 0.88, 1.0, max(vLit * 0.85, vHeat * 0.90)), 0.28, 1.0);
      float a = falloff * mix(brainA, vAlpha, vMorph) * uOpacity;
      gl_FragColor = vec4(col, a);
    }
  `;

  // ---------------------------------------------------------------------
  // NeuralBrain Class
  // ---------------------------------------------------------------------

  class NeuralBrain {
    constructor(canvas, options = {}) {
      if (typeof global.THREE === 'undefined') {
        throw new Error('three.js must be loaded before neural-brain.js');
      }
      const T = global.THREE;

      this.canvas = canvas;
      this.reduceMotion = global.matchMedia('(prefers-reduced-motion: reduce)').matches;

      const dpr = Math.min(global.devicePixelRatio || 1, 2);
      const wide = Math.max(canvas.clientWidth || 0, global.innerWidth) > 900;
      this.count = options.count || (wide ? 115000 : 55000);

      // --- Scene & Camera ---
      this.scene = new T.Scene();
      this.camera = new T.PerspectiveCamera(
        36, canvas.clientWidth / Math.max(canvas.clientHeight, 1), 0.1, 200
      );
      this.camera.position.set(0, 0, 4.2);

      this.renderer = new T.WebGLRenderer({
        canvas,
        antialias: false,
        alpha: true,
        powerPreference: 'high-performance',
      });
      this.renderer.setPixelRatio(dpr);
      this.renderer.setClearColor(0x000000, 0);

      // --- Geometry ---
      const data = buildBrain(this.count, options.seed || 20260817);

      const geo = new T.BufferGeometry();
      geo.setAttribute('position', new T.BufferAttribute(data.pos, 3));
      geo.setAttribute('aScatter', new T.BufferAttribute(data.scatter, 3));
      geo.setAttribute('aSize', new T.BufferAttribute(data.size, 1));
      geo.setAttribute('aAlpha', new T.BufferAttribute(data.alpha, 1));
      geo.setAttribute('aRegion', new T.BufferAttribute(data.region, 1));
      geo.setAttribute('aSeed', new T.BufferAttribute(data.seed, 1));
      geo.setAttribute('aNormal', new T.BufferAttribute(data.normal, 3));
      geo.setAttribute('aElev', new T.BufferAttribute(data.elev, 1));

      // VISIBLE MATTE BLUE PALETTE (MATCHING IMAGE 2, ZERO SHINE, NO WHITE)
      this.uniforms = {
        uTime:        { value: 0 },
        uMorph:       { value: 0 },
        uPulse:       { value: -1 },
        uFocus:       { value: new T.Vector3(0, 0, 0) },
        uFocusRadius: { value: 0 },
        uCursor:      { value: new T.Vector2(0, 0) },
        uCursorOn:    { value: 0 },
        uAspect:      { value: new T.Vector2(1, 1) },
        uPixelRatio:  { value: dpr },
        uScale:       { value: wide ? 0.82 : 0.70 },
        uColorDark:   { value: new T.Color('#072464') }, // rich navy shadow (lifted so not pitch black)
        uColorMid:    { value: new T.Color('#1d64f2') }, // visible royal blue
        uColorLit:    { value: new T.Color('#50c4ff') }, // luminous cyan crest
        uOpacity:     { value: 1.0 },
      };

      this.material = new T.ShaderMaterial({
        uniforms: this.uniforms,
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        transparent: true,
        depthWrite: false,
        blending: T.NormalBlending,
      });

      this.points = new T.Points(geo, this.material);

      // --- Constellation Lines (Disabled per user request: "no lines only particles") ---
      const lineVerts = buildNetworkLines(
        data.scatter, this.count, 400, options.seed || 20260817
      );
      const lineGeo = new T.BufferGeometry();
      lineGeo.setAttribute('position', new T.BufferAttribute(lineVerts, 3));
      this.lineMaterial = new T.LineBasicMaterial({
        color: new T.Color('#2563eb'),
        transparent: true,
        opacity: 0,
        blending: T.NormalBlending,
        depthWrite: false,
      });
      this.lines = new T.LineSegments(lineGeo, this.lineMaterial);
      this.lines.visible = false; // Strictly hidden: NO geometrical lines

      // --- Group ---
      this.group = new T.Group();
      this.group.add(this.points);
      this.group.add(this.lines);

      // Anatomical forward tilt matching Image 2
      this.group.rotation.x = 0.14;
      this.group.rotation.y = 0.0; // Locked facing forward (NO ROTATION)
      this.scene.add(this.group);

      // --- Atmospheric Back Glow (Separates brain from dull background) ---
      const backGlowGeo = new T.PlaneGeometry(3.2, 2.9, 1, 1);
      this.backGlowMaterial = new T.ShaderMaterial({
        uniforms: {
          uTime: this.uniforms.uTime,
          uMorph: this.uniforms.uMorph,
          uOpacity: this.uniforms.uOpacity,
        },
        vertexShader: `
          varying vec2 vUv;
          void main() {
            vUv = uv;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          precision mediump float;
          varying vec2 vUv;
          uniform float uTime;
          uniform float uMorph;
          uniform float uOpacity;

          void main() {
            vec2 p = (vUv - vec2(0.5, 0.48)) * vec2(1.12, 1.0);
            float d = length(p);

            float breathe = 0.94 + 0.06 * sin(uTime * 1.4);

            // Multi-tier radial aura tuned to cradle the brain silhouette
            float core = smoothstep(0.48, 0.02, d) * 0.58;
            float halo = smoothstep(0.95, 0.05, d) * 0.34;
            float aura = max(core, halo) * breathe;

            // Electric cyan inner core transitioning to deep royal celestial blue
            vec3 coreCol = vec3(0.09, 0.58, 0.98); // vibrant electric cyan/azure
            vec3 haloCol = vec3(0.05, 0.24, 0.72); // royal celestial blue
            vec3 col = mix(haloCol, coreCol, core / max(core + halo, 0.001));

            float a = aura * (1.0 - uMorph) * uOpacity;
            if (a < 0.001) discard;

            gl_FragColor = vec4(col * a, 0.0);
          }
        `,
        transparent: true,
        depthWrite: false,
        blending: T.AdditiveBlending,
      });

      this.backGlow = new T.Mesh(backGlowGeo, this.backGlowMaterial);
      this.backGlow.position.set(0, 0.10, -0.65);
      this.scene.add(this.backGlow);

      // --- Interaction ---
      this.pointer = { x: 0, y: 0 };
      this.parallax = { x: 0, y: 0 };
      this.autoSpin = 0.0; // ROTATION COMPLETELY DISABLED
      this.cameraTarget = new T.Vector3(0, 0.145, 0);

      this._camX = 0;
      this._camY = 0.10;
      this._camZ = 2.95;
      this._viewOffsetX = 0;
      this.camera.position.set(0, 0.10, 2.95);

      this._onPointerMove = (e) => {
        this.pointer.x = (e.clientX / global.innerWidth) * 2 - 1;
        this.pointer.y = (e.clientY / global.innerHeight) * 2 - 1;
        this.setCursor([e.clientX, e.clientY]);
      };
      this._onPointerLeave = () => {
        this.setCursor(null);
      };
      global.addEventListener('pointermove', this._onPointerMove, { passive: true });
      document.addEventListener('mouseleave', this._onPointerLeave);

      this._onResize = () => this.resize();
      global.addEventListener('resize', this._onResize);

      this.resize();
      this.clock = new T.Clock();
      this._running = false;
    }

    updateViewOffset() {
      const w = this.canvas.clientWidth || global.innerWidth;
      const h = this.canvas.clientHeight || global.innerHeight;
      if (this._viewOffsetX && Math.abs(this._viewOffsetX) > 0.001) {
        this.camera.setViewOffset(w, h, -this._viewOffsetX * w, 0, w, h);
      } else {
        this.camera.clearViewOffset();
      }
    }

    resize() {
      const w = this.canvas.clientWidth || global.innerWidth;
      const h = this.canvas.clientHeight || global.innerHeight;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / Math.max(h, 1);
      this.updateViewOffset();
      this.camera.updateProjectionMatrix();
      this.uniforms.uScale.value = w > 900 ? 0.82 : 0.70;
      this.uniforms.uAspect.value.set(Math.max(w / h, 1), Math.max(h / w, 1));
      const glowScale = w > 900 ? 1.0 : 0.85;
      if (this.backGlow) this.backGlow.scale.set(glowScale, glowScale, 1);
    }

    start() {
      if (this._running) return;
      this._running = true;
      const tick = () => {
        if (!this._running) return;
        this._frame = requestAnimationFrame(tick);
        this.render();
      };
      tick();
    }

    stop() {
      this._running = false;
      if (this._frame) cancelAnimationFrame(this._frame);
    }

    dispose() {
      this.stop();
      global.removeEventListener('pointermove', this._onPointerMove);
      document.removeEventListener('mouseleave', this._onPointerLeave);
      global.removeEventListener('resize', this._onResize);
      this.points.geometry.dispose();
      this.lines.geometry.dispose();
      this.material.dispose();
      this.lineMaterial.dispose();
      if (this.backGlow) {
        this.scene.remove(this.backGlow);
        this.backGlow.geometry.dispose();
        this.backGlowMaterial.dispose();
      }
      this.renderer.dispose();
    }

    render() {
      const dt = Math.min(this.clock.getDelta(), 0.05);
      this.uniforms.uTime.value += dt;

      // Subtle mouse parallax (brain orientation itself is locked, no auto-spin)
      if (!this.reduceMotion) {
        this.parallax.x += (this.pointer.x * 0.10 - this.parallax.x) * 0.045;
        this.parallax.y += (this.pointer.y * 0.06 - this.parallax.y) * 0.045;
      }

      const cam = this.camera;
      cam.position.x = this._camX + this.parallax.x;
      cam.position.y = this._camY - this.parallax.y;
      cam.position.z = this._camZ;
      cam.lookAt(this.cameraTarget);

      if (this.backGlow) {
        this.backGlow.quaternion.copy(cam.quaternion);
      }

      this.renderer.render(this.scene, cam);
    }

    get camX() { return this._camX; }  set camX(v) { this._camX = v; }
    get camY() { return this._camY; }  set camY(v) { this._camY = v; }
    get camZ() { return this._camZ; }  set camZ(v) { this._camZ = v; }

    get beaconOpacity() { return 0; }
    set beaconOpacity(v) {}
    get beaconScale() { return 0; }
    set beaconScale(v) {}

    get viewOffsetX() { return this._viewOffsetX; }
    set viewOffsetX(v) {
      if (Math.abs(this._viewOffsetX - v) < 0.0001) return;
      this._viewOffsetX = v;
      this.updateViewOffset();
    }

    setCursor(pos) {
      if (!pos) { this.uniforms.uCursorOn.value = 0; return; }
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) { this.uniforms.uCursorOn.value = 0; return; }
      this.uniforms.uCursor.value.set(
        ((pos[0] - rect.left) / rect.width) * 2 - 1,
        -(((pos[1] - rect.top) / rect.height) * 2 - 1)
      );
      this.uniforms.uCursorOn.value = 1;
    }

    setFocus(x, y, z, radius) {
      this.uniforms.uFocus.value.set(x, y, z);
      this.uniforms.uFocusRadius.value = radius;
    }
  }

  NeuralBrain.buildBrain = buildBrain;
  global.NeuralBrain = NeuralBrain;
})(window);
