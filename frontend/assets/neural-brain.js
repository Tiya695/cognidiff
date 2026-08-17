/* CogniDiff, procedural brain point cloud.
 *
 * The brain is generated, not loaded: a folded implicit surface sampled into
 * ~90k points, plus a cerebellum, a brainstem and an interior volume for depth.
 * Rendered as additive-blended sprites so overlapping particles build up glow
 * the way a real scan does.
 *
 * Every state the page scrolls through is a uniform on one shader:
 *   uMorph      0 → brain, 1 → dispersed constellation
 *   uPulse      travelling signal wave along the anterior–posterior axis
 *   uFocus      xyz centre + radius of a highlighted region
 *
 * Exposes window.NeuralBrain.
 */

(function (global) {
  'use strict';

  // ---------------------------------------------------------------------
  // deterministic noise (so the brain looks identical on every load)
  // ---------------------------------------------------------------------

  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Classic 3D value noise with smooth interpolation, enough for gyri.
  function makeNoise3(rand) {
    const SIZE = 64;
    const table = new Float32Array(SIZE * SIZE * SIZE);
    for (let i = 0; i < table.length; i++) table[i] = rand();

    const at = (x, y, z) =>
      table[(((x & 63) * SIZE + (y & 63)) * SIZE) + (z & 63)];

    const fade = (t) => t * t * (3 - 2 * t);
    const lerp = (a, b, t) => a + (b - a) * t;

    return function noise(x, y, z) {
      const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
      const xf = fade(x - xi), yf = fade(y - yi), zf = fade(z - zi);

      const c000 = at(xi, yi, zi),         c100 = at(xi + 1, yi, zi);
      const c010 = at(xi, yi + 1, zi),     c110 = at(xi + 1, yi + 1, zi);
      const c001 = at(xi, yi, zi + 1),     c101 = at(xi + 1, yi, zi + 1);
      const c011 = at(xi, yi + 1, zi + 1), c111 = at(xi + 1, yi + 1, zi + 1);

      return lerp(
        lerp(lerp(c000, c100, xf), lerp(c010, c110, xf), yf),
        lerp(lerp(c001, c101, xf), lerp(c011, c111, xf), yf),
        zf
      );
    };
  }

  // ---------------------------------------------------------------------
  // brain geometry
  // ---------------------------------------------------------------------

  /**
   * Cerebral surface in a given unit direction.
   * Built from an ellipsoid, then sculpted: tapered at the frontal pole,
   * bulged at the temporal lobes, flattened underneath, split by the
   * longitudinal fissure, and folded by layered noise to make gyri and sulci.
   *
   * Returns { r, fold }, `fold` is 0 in a sulcus and 1 on a gyral crown, and
   * is used to modulate particle brightness. That is what makes the folds
   * legible: a uniformly lit shell reads as sand, whereas brightening the
   * ridges makes the surface look like the convoluted thing it is.
   */
  function cerebrumSurface(x, y, z, noise) {
    const RX = 0.87, RY = 0.96, RZ = 1.14;

    // base ellipsoid
    let r = 1 / Math.sqrt((x / RX) ** 2 + (y / RY) ** 2 + (z / RZ) ** 2);

    // frontal pole is narrower than the occipital pole
    if (z > 0) r *= 1 - 0.12 * Math.pow(z, 2);
    // occipital pole tucks in slightly
    if (z < -0.6) r *= 1 - 0.09 * Math.pow(-z - 0.6, 1.5);

    // temporal lobes: bulge low and to the sides, forward of centre
    const temporal = Math.max(0, -y - 0.02) * Math.max(0, Math.abs(x) - 0.22)
                     * Math.max(0, 0.88 - Math.abs(z + 0.1));
    r *= 1 + 1.25 * temporal;

    // the underside of the cerebrum is flatter than a sphere, but not a plane
    if (y < -0.52) r *= 1 - 0.30 * Math.pow(-y - 0.52, 1.3);

    // longitudinal fissure, the deep midline groove between hemispheres
    const midline = Math.exp(-(x * x) / 0.0026);
    r *= 1 - 0.20 * midline * Math.max(0, y + 0.05);

    // central + lateral sulci, as broad grooves rather than noise
    const central = Math.exp(-Math.pow((z - 0.02) * 3.1 - y * 1.4, 2) * 5.0);
    r *= 1 - 0.040 * central;
    const lateral = Math.exp(-Math.pow((y + 0.18) * 4.4 + (z + 0.1) * 0.8, 2) * 4.0)
                    * Math.min(1, Math.abs(x) * 2.2);
    r *= 1 - 0.050 * lateral;

    // gyri: two octaves, coarse enough to read as folds rather than grain
    const n1 = noise(x * 4.3 + 11, y * 4.3 + 23, z * 4.3 + 37);
    const n2 = noise(x * 9.1 + 3,  y * 9.1 + 61, z * 9.1 + 17);
    r *= 1 + 0.085 * (n1 - 0.5) + 0.038 * (n2 - 0.5);

    // ridged noise: peaks along the crests, which is where the bright
    // filaments in a real point-cloud scan appear
    const ridge = (1 - Math.abs(n1 * 2 - 1)) * 0.68
                + (1 - Math.abs(n2 * 2 - 1)) * 0.32;
    const fold = Math.pow(Math.max(0, Math.min(1, ridge)), 2.1);

    return { r, fold, groove: Math.max(central, lateral, midline) };
  }

  function randomDirection(rand) {
    // Uniform on the sphere via inverse-CDF on cos(theta).
    const u = rand() * 2 - 1;
    const phi = rand() * Math.PI * 2;
    const s = Math.sqrt(Math.max(0, 1 - u * u));
    return [s * Math.cos(phi), u, s * Math.sin(phi)];
  }

  /**
   * Build the full point cloud.
   * Returns positions, scatter targets, sizes, alphas and a region id per point.
   *   region 0 = cerebral surface, 1 = interior, 2 = cerebellum, 3 = brainstem
   */
  function buildBrain(count, seed) {
    const rand = mulberry32(seed);
    const noise = makeNoise3(mulberry32(seed ^ 0x9e3779b9));

    // Weighted toward the surface: the shell is what carries the shape, and a
    // dense interior just fills the silhouette in and hides the folds.
    const nSurface = Math.floor(count * 0.70);
    const nInterior = Math.floor(count * 0.08);
    const nCerebellum = Math.floor(count * 0.13);
    const nStem = count - nSurface - nInterior - nCerebellum;

    const pos = new Float32Array(count * 3);
    const scatter = new Float32Array(count * 3);
    const size = new Float32Array(count);
    const alpha = new Float32Array(count);
    const region = new Float32Array(count);
    const seedAttr = new Float32Array(count);

    let i = 0;
    const push = (x, y, z, s, a, reg) => {
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
      size[i] = s; alpha[i] = a; region[i] = reg; seedAttr[i] = rand();

      // Constellation target: a wide, sparse shell with clustered nodes, so
      // the dispersed state reads as a star map rather than a cloud of dust.
      const d = randomDirection(rand);
      const spread = 1.9 + Math.pow(rand(), 0.7) * 2.3;
      scatter[i * 3]     = d[0] * spread * 1.35;
      scatter[i * 3 + 1] = d[1] * spread * 0.85;
      scatter[i * 3 + 2] = d[2] * spread * 1.00;
      i++;
    };

    // --- cerebral surface ---------------------------------------------
    // Points are rejection-sampled toward the gyral crowns rather than spread
    // evenly. Brightness alone was not enough, an evenly scattered shell reads
    // as grain no matter how it is shaded, whereas biasing the *placement*
    // makes the particles themselves trace the folds, which is what gives a
    // real point-cloud scan its filamentary look.
    let placed = 0, guard = 0;
    while (placed < nSurface && guard < nSurface * 40) {
      guard++;
      const [dx, dy, dz] = randomDirection(rand);
      const { r, fold, groove } = cerebrumSurface(dx, dy, dz, noise);

      if (rand() > 0.16 + 0.84 * fold) continue;      // reject sulcal floors

      const jitter = 1 - rand() * 0.030;
      const brightness = (0.28 + 0.90 * fold) * (1 - 0.50 * groove);
      push(
        dx * r * jitter,
        dy * r * jitter + 0.06,
        dz * r * jitter,
        0.32 + rand() * 0.38 + fold * 0.30,
        Math.min(0.58, 0.045 + rand() * 0.105 + brightness * 0.30),
        0
      );
      placed++;
    }

    // --- interior volume (depth cue) -----------------------------------
    // Sparse and dim on purpose: enough to suggest volume behind the shell,
    // never enough to fill the silhouette in.
    for (let k = 0; k < nInterior; k++) {
      const [dx, dy, dz] = randomDirection(rand);
      const { r } = cerebrumSurface(dx, dy, dz, noise);
      const depth = 0.30 + rand() * 0.58;
      push(
        dx * r * depth, dy * r * depth + 0.06, dz * r * depth,
        0.24 + rand() * 0.22,
        0.020 + rand() * 0.048,
        1
      );
    }

    // --- cerebellum ------------------------------------------------------
    // Two lobes below and behind the cerebrum, with its characteristic fine
    // horizontal foliation.
    const CB = { x: 0, y: -0.60, z: -0.74 };
    for (let k = 0; k < nCerebellum; k++) {
      const [dx, dy, dz] = randomDirection(rand);
      let r = 1 / Math.sqrt((dx / 0.60) ** 2 + (dy / 0.30) ** 2 + (dz / 0.40) ** 2);
      r *= 1 + 0.05 * (noise(dx * 9 + 5, dy * 34 + 9, dz * 9 + 2) - 0.5); // foliation
      const midline = Math.exp(-(dx * dx) / 0.004);
      r *= 1 - 0.13 * midline;
      const shell = 1 - rand() * 0.30;
      push(
        CB.x + dx * r * shell,
        CB.y + dy * r * shell,
        CB.z + dz * r * shell,
        0.34 + rand() * 0.40,
        0.075 + rand() * 0.235,
        2
      );
    }

    // --- brainstem --------------------------------------------------------
    for (let k = 0; k < nStem; k++) {
      const t = rand();                        // 0 top → 1 bottom
      // shell-weighted so the column has edges instead of fading to fog
      const rad = (0.185 - 0.055 * t) * (0.80 + rand() * 0.20);
      const ang = rand() * Math.PI * 2;
      push(
        Math.cos(ang) * rad,
        -0.46 - t * 0.62,
        -0.20 + Math.sin(ang) * rad * 0.85,
        0.32 + rand() * 0.30,
        0.070 + rand() * 0.190,
        3
      );
    }

    return { pos, scatter, size, alpha, region, seed: seedAttr, count };
  }

  /** Pick node pairs for the constellation lines drawn in the network state. */
  function buildNetworkLines(scatter, count, maxLines, seed) {
    const rand = mulberry32(seed ^ 0x51ed270b);
    const nodes = [];
    const stride = Math.max(1, Math.floor(count / 340));
    for (let i = 0; i < count; i += stride) {
      nodes.push([scatter[i * 3], scatter[i * 3 + 1], scatter[i * 3 + 2]]);
    }

    const verts = [];
    for (let a = 0; a < nodes.length && verts.length / 6 < maxLines; a++) {
      // connect each node to its nearest few neighbours, that local structure
      // is what makes it read as a network instead of random chords
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
  // shaders
  // ---------------------------------------------------------------------

  const VERTEX = `
    attribute vec3  aScatter;
    attribute float aSize;
    attribute float aAlpha;
    attribute float aRegion;
    attribute float aSeed;

    uniform float uTime;
    uniform float uMorph;        // 0 brain, 1 constellation
    uniform float uPulse;        // -1 = off, else 0..1 sweep position
    uniform vec3  uFocus;        // highlighted region centre
    uniform float uFocusRadius;  // 0 = no highlight
    uniform vec2  uCursor;       // pointer in clip space
    uniform float uCursorOn;     // 0 = pointer has left the window
    uniform vec2  uAspect;
    uniform float uPixelRatio;
    uniform float uScale;

    varying float vAlpha;
    varying float vHeat;         // 0 base cyan → 1 hot white-cyan

    void main() {
      // idle drift keeps the cloud alive even when nothing is scrolling
      vec3 drift = vec3(
        sin(uTime * 0.35 + aSeed * 21.0),
        cos(uTime * 0.29 + aSeed * 17.0),
        sin(uTime * 0.31 + aSeed * 13.0)
      ) * 0.006;

      // ease the morph per particle so the dispersal ripples outward
      float stagger = clamp(uMorph * 1.6 - aSeed * 0.6, 0.0, 1.0);
      float m = stagger * stagger * (3.0 - 2.0 * stagger);
      vec3 p = mix(position + drift, aScatter, m);

      float heat = 0.0;

      // travelling signal wave along the anterior–posterior axis
      if (uPulse >= 0.0) {
        float axis  = (position.z + 1.35) / 2.7;          // 0 back → 1 front
        float band  = abs(axis - uPulse);
        heat = max(heat, smoothstep(0.15, 0.02, band) * 0.75 * (1.0 - m));
      }

      // region highlight (occipital pole, cerebellum, …)
      if (uFocusRadius > 0.0) {
        float d = distance(position, uFocus);
        // stops short of full intensity at the centre so the highlight reads
        // as a bloom on the region rather than a hole burned through it
        heat = max(heat, smoothstep(uFocusRadius, uFocusRadius * 0.55, d) * 0.7 * (1.0 - m));
      }

      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_Position = projectionMatrix * mv;

      // The cursor is a light source: particles near it, in screen space, lift.
      // Screen space rather than world space on purpose, so the light behaves
      // like something held in front of the scan rather than buried inside it.
      float lit = 0.0;
      if (uCursorOn > 0.5 && gl_Position.w > 0.0) {
        vec2 ndc = gl_Position.xy / gl_Position.w;
        float d = length((ndc - uCursor) * uAspect);
        lit = smoothstep(0.55, 0.0, d);
      }

      vHeat = max(heat, lit * 0.45);
      vAlpha = aAlpha * mix(1.0, 1.30, m) + heat * 0.07 + lit * 0.10;

      float s = aSize * uScale * (1.0 + heat * 0.75 + lit * 0.30);
      gl_PointSize = s * uPixelRatio * (34.0 / max(-mv.z, 0.1));
    }
  `;

  const FRAGMENT = `
    precision mediump float;

    uniform vec3 uColor;
    uniform vec3 uHotColor;
    uniform float uOpacity;

    varying float vAlpha;
    varying float vHeat;

    void main() {
      // round sprite with a soft falloff, no texture needed
      vec2 c = gl_PointCoord - vec2(0.5);
      float d = dot(c, c);
      if (d > 0.25) discard;

      float falloff = 1.0 - smoothstep(0.0, 0.25, d);
      falloff = pow(falloff, 2.3);

      vec3 col = mix(uColor, uHotColor, vHeat);
      gl_FragColor = vec4(col, falloff * vAlpha * uOpacity);
    }
  `;

  // ---------------------------------------------------------------------
  // the renderer
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
      const wide = global.innerWidth > 900;
      this.count = options.count || (wide ? 90000 : 34000);

      // --- scene ---------------------------------------------------------
      this.scene = new T.Scene();
      this.camera = new T.PerspectiveCamera(
        42, canvas.clientWidth / Math.max(canvas.clientHeight, 1), 0.1, 200
      );
      this.camera.position.set(0, 0, 4.2);

      this.renderer = new T.WebGLRenderer({
        canvas, antialias: false, alpha: true, powerPreference: 'high-performance',
      });
      this.renderer.setPixelRatio(dpr);
      this.renderer.setClearColor(0x000000, 0);

      // --- geometry ------------------------------------------------------
      const data = buildBrain(this.count, options.seed || 20260817);

      const geo = new T.BufferGeometry();
      geo.setAttribute('position', new T.BufferAttribute(data.pos, 3));
      geo.setAttribute('aScatter', new T.BufferAttribute(data.scatter, 3));
      geo.setAttribute('aSize', new T.BufferAttribute(data.size, 1));
      geo.setAttribute('aAlpha', new T.BufferAttribute(data.alpha, 1));
      geo.setAttribute('aRegion', new T.BufferAttribute(data.region, 1));
      geo.setAttribute('aSeed', new T.BufferAttribute(data.seed, 1));

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
        uScale:       { value: wide ? 1.0 : 0.85 },
        uColor:       { value: new T.Color(options.color || '#5ec8f5') },
        uHotColor:    { value: new T.Color(options.hotColor || '#a9e8ff') },
        uOpacity:     { value: 1 },
      };

      this.material = new T.ShaderMaterial({
        uniforms: this.uniforms,
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        transparent: true,
        depthWrite: false,
        blending: T.AdditiveBlending,
      });

      this.points = new T.Points(geo, this.material);

      // --- constellation lines --------------------------------------------
      const lineVerts = buildNetworkLines(
        data.scatter, this.count, 420, options.seed || 20260817
      );
      const lineGeo = new T.BufferGeometry();
      lineGeo.setAttribute('position', new T.BufferAttribute(lineVerts, 3));
      this.lineMaterial = new T.LineBasicMaterial({
        color: new T.Color('#4f9fd8'),
        transparent: true,
        opacity: 0,
        blending: T.AdditiveBlending,
        depthWrite: false,
      });
      this.lines = new T.LineSegments(lineGeo, this.lineMaterial);

      // --- group ------------------------------------------------------------
      this.group = new T.Group();
      this.group.add(this.points);
      this.group.add(this.lines);
      this.scene.add(this.group);

      // --- interaction ------------------------------------------------------
      this.pointer = { x: 0, y: 0 };
      this.parallax = { x: 0, y: 0 };
      this.autoSpin = 0.055;
      this.cameraTarget = new T.Vector3(0, 0, 0);

      this._onPointerMove = (e) => {
        this.pointer.x = (e.clientX / global.innerWidth) * 2 - 1;
        this.pointer.y = (e.clientY / global.innerHeight) * 2 - 1;
      };
      global.addEventListener('pointermove', this._onPointerMove, { passive: true });

      this._onResize = () => this.resize();
      global.addEventListener('resize', this._onResize);

      this.resize();
      this.clock = new T.Clock();
      this._running = false;
    }

    resize() {
      const w = this.canvas.clientWidth || global.innerWidth;
      const h = this.canvas.clientHeight || global.innerHeight;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / Math.max(h, 1);
      this.camera.updateProjectionMatrix();
      this.uniforms.uScale.value = w > 900 ? 1.0 : 0.85;
      this.uniforms.uAspect.value.set(Math.max(w / h, 1), Math.max(h / w, 1));
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
      global.removeEventListener('resize', this._onResize);
      this.points.geometry.dispose();
      this.lines.geometry.dispose();
      this.material.dispose();
      this.lineMaterial.dispose();
      this.renderer.dispose();
    }

    render() {
      const dt = Math.min(this.clock.getDelta(), 0.05);
      this.uniforms.uTime.value += dt;

      if (!this.reduceMotion) {
        this.group.rotation.y += this.autoSpin * dt;

        // mouse parallax, eased, the depth cue that makes it feel volumetric
        this.parallax.x += (this.pointer.x * 0.18 - this.parallax.x) * 0.045;
        this.parallax.y += (this.pointer.y * 0.12 - this.parallax.y) * 0.045;
      }

      const cam = this.camera;
      cam.position.x = this._camX + this.parallax.x;
      cam.position.y = this._camY - this.parallax.y;
      cam.position.z = this._camZ;
      cam.lookAt(this.cameraTarget);

      this.renderer.render(this.scene, cam);
    }

    // -- state control ----------------------------------------------------

    /** Camera position, set directly (GSAP tweens these three numbers). */
    get camX() { return this._camX ?? 0; }  set camX(v) { this._camX = v; }
    get camY() { return this._camY ?? 0; }  set camY(v) { this._camY = v; }
    get camZ() { return this._camZ ?? 4.2; } set camZ(v) { this._camZ = v; }

    /** Pointer position in CSS pixels, or null when it has left the window. */
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
