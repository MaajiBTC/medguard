import { useEffect, useRef } from 'react';
import * as THREE from 'three';

// CLAUDE.md scopes three.js to exactly two places: this login/landing page and the
// Security Dashboard visualization (LedgerVisualization.jsx). Purely decorative --
// the actual login form is plain HTML/React; this is just the animated brand shield
// beside it. A plum shield body with a hospital cross emblem on its front face and a
// smaller shield emblem on its back -- both revealed during the 360-degree entrance spin.

const PLUM = 0x6528d9;
const PLUM_DEEP = 0x2a0f5c;
const WHITE = 0xffffff;

function buildCrossShape() {
  const w = 0.22; // half-width of the cross arms
  const l = 0.62; // half-length of the cross arms
  const shape = new THREE.Shape();
  shape.moveTo(-w, -l);
  shape.lineTo(w, -l);
  shape.lineTo(w, -w);
  shape.lineTo(l, -w);
  shape.lineTo(l, w);
  shape.lineTo(w, w);
  shape.lineTo(w, l);
  shape.lineTo(-w, l);
  shape.lineTo(-w, w);
  shape.lineTo(-l, w);
  shape.lineTo(-l, -w);
  shape.lineTo(-w, -w);
  shape.lineTo(-w, -l);
  return shape;
}

function buildShieldShape() {
  const shape = new THREE.Shape();
  shape.moveTo(-0.95, 0.55);
  shape.bezierCurveTo(-0.95, 0.95, -0.5, 1.1, 0, 1.15);
  shape.bezierCurveTo(0.5, 1.1, 0.95, 0.95, 0.95, 0.55);
  shape.lineTo(0.9, -0.15);
  shape.bezierCurveTo(0.85, -0.85, 0.4, -1.15, 0, -1.35);
  shape.bezierCurveTo(-0.4, -1.15, -0.85, -0.85, -0.9, -0.15);
  shape.lineTo(-0.95, 0.55);
  return shape;
}

// A soft radial-gradient blob (white center fading smoothly to fully transparent) --
// used as a texture on camera-facing sprites so glows have zero hard edge/boundary,
// unlike a flat oversized copy of a shape (which just shows a bigger silhouette).
function createGlowTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.25, 'rgba(255,255,255,0.85)');
  gradient.addColorStop(0.55, 'rgba(255,255,255,0.3)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

function easeOutBack(x) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2;
}

function easeOutCubic(x) {
  return 1 - (1 - x) ** 3;
}

const ENTRANCE_MS = 1300;
const SHIELD_DEPTH = 0.28;
const EMBLEM_DEPTH = 0.24;

/** Animated shield for the login page's brand panel: a plum shield body that spins a
 * full 360 degrees while popping in (overshoot ease on scale, decelerating spin on
 * rotation), revealing the hospital cross on its front and a shield emblem on its
 * back before settling to a stop facing forward (cross side). Idles with a gentle
 * sway + bob afterward, plus a softly pulsing glow (radial-gradient sprites, no
 * hard edges) behind the ring, cross, and back shield. Respects
 * prefers-reduced-motion (renders the settled shield, front-facing, with no spin). */
function LoginScene() {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const width = mount.clientWidth;
    const height = mount.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
    camera.position.set(0, 0, 4.2);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const glowTexture = createGlowTexture();
    const glowSprites = []; // { sprite, material, baseOpacity }
    function addGlowSprite(parent, { scale, baseOpacity, z = 0 }) {
      const material = new THREE.SpriteMaterial({
        map: glowTexture,
        color: WHITE,
        transparent: true,
        opacity: reduceMotion ? baseOpacity : 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const sprite = new THREE.Sprite(material);
      sprite.scale.set(scale, scale, 1);
      sprite.position.z = z;
      parent.add(sprite);
      glowSprites.push({ material, baseOpacity });
      return material;
    }

    const medallion = new THREE.Group();
    scene.add(medallion);

    // Body: the shield silhouette itself (unchanged shape), not a separate coin.
    const shieldGeometry = new THREE.ExtrudeGeometry(buildShieldShape(), {
      depth: SHIELD_DEPTH,
      bevelEnabled: true,
      bevelThickness: 0.06,
      bevelSize: 0.05,
      bevelSegments: 4,
      curveSegments: 24,
    });
    shieldGeometry.center();
    const shieldMaterial = new THREE.MeshStandardMaterial({
      color: PLUM,
      emissive: PLUM_DEEP,
      emissiveIntensity: 0.25,
      metalness: 0.35,
      roughness: 0.4,
    });
    const shield = new THREE.Mesh(shieldGeometry, shieldMaterial);
    medallion.add(shield);

    // Front face: a hospital cross emblem (unchanged shape), sitting proud of the shield.
    const crossGeometry = new THREE.ExtrudeGeometry(buildCrossShape(), {
      depth: EMBLEM_DEPTH,
      bevelEnabled: true,
      bevelThickness: 0.0375,
      bevelSize: 0.0375,
      bevelSegments: 2,
      curveSegments: 8,
    });
    // Unlit (MeshBasicMaterial, like the ring below) -- MeshStandardMaterial still
    // shades/tints a "white" surface under colored scene lighting, which read as
    // gray/lavender instead of pure white. Unlit ignores lighting entirely.
    const crossMaterial = new THREE.MeshBasicMaterial({ color: WHITE });
    const cross = new THREE.Mesh(crossGeometry, crossMaterial);
    cross.position.z = SHIELD_DEPTH / 2;
    medallion.add(cross);

    addGlowSprite(medallion, { scale: 2.4, baseOpacity: 0.7, z: cross.position.z + EMBLEM_DEPTH / 2 });

    // Back face: a smaller shield emblem (unchanged shape), revealed as the shield
    // spins during entrance -- distinct from the body's own outer silhouette.
    const backShieldGeometry = new THREE.ExtrudeGeometry(buildShieldShape(), {
      depth: EMBLEM_DEPTH,
      bevelEnabled: true,
      bevelThickness: 0.0375,
      bevelSize: 0.0375,
      bevelSegments: 2,
      curveSegments: 16,
    });
    backShieldGeometry.center();
    const backShieldMaterial = new THREE.MeshBasicMaterial({ color: WHITE });
    const backShield = new THREE.Mesh(backShieldGeometry, backShieldMaterial);
    backShield.scale.set(0.62, 0.62, 1);
    backShield.position.z = -(SHIELD_DEPTH / 2 + EMBLEM_DEPTH / 2);
    medallion.add(backShield);

    addGlowSprite(medallion, { scale: 1.9, baseOpacity: 0.65, z: backShield.position.z - EMBLEM_DEPTH / 2 });

    medallion.scale.setScalar(reduceMotion ? 1 : 0.001);
    medallion.rotation.y = reduceMotion ? 0 : -Math.PI * 2;

    const ringGeometry = new THREE.TorusGeometry(1.5, 0.03, 12, 96);
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: WHITE,
      transparent: true,
      opacity: reduceMotion ? 1 : 0,
    });
    const ring = new THREE.Mesh(ringGeometry, ringMaterial);
    ring.rotation.x = Math.PI / 2.4;
    scene.add(ring);

    // One big soft sprite centered on the ring rather than a second, thicker torus --
    // a torus copy would still show its own tube-shaped edge; a radial-gradient
    // sprite blends smoothly into the ring (and the shield behind it) with no boundary.
    addGlowSprite(scene, { scale: 3.6, baseOpacity: 0.75 });

    // Lavender key light for shading/depth on the shield body -- lighting only, not
    // an object color (the cross/shield/ring are unlit and pure white regardless).
    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    const key = new THREE.PointLight(0xc4b5fd, 1.4);
    key.position.set(2, 2, 3);
    const rim = new THREE.PointLight(PLUM, 0.9);
    rim.position.set(-3, -1, -2);
    scene.add(ambient, key, rim);

    let frameId;
    const start = performance.now();
    const animate = (now) => {
      if (reduceMotion) {
        ring.rotation.z += 0.001;
        renderer.render(scene, camera);
        frameId = requestAnimationFrame(animate);
        return;
      }

      const elapsed = now - start;
      const t = Math.min(elapsed / ENTRANCE_MS, 1);
      const scaleEased = easeOutBack(t);
      medallion.scale.setScalar(Math.max(scaleEased, 0.001));

      if (t < 1) {
        // One full 360-degree turn, decelerating to a stop facing forward (cross-side).
        medallion.rotation.y = -Math.PI * 2 * (1 - easeOutCubic(t));
      } else {
        const idleElapsed = elapsed - ENTRANCE_MS;
        medallion.rotation.y = Math.sin(idleElapsed / 1800) * 0.12;
      }
      medallion.position.y = Math.sin(elapsed / 1400) * 0.06;
      ring.material.opacity = t;
      ring.rotation.z += 0.0035;

      // Gentle breathing glow (illuminated look) on top of the entrance fade-in.
      const pulse = 0.75 + 0.25 * Math.sin(elapsed / 900);
      glowSprites.forEach(({ material, baseOpacity }) => {
        material.opacity = baseOpacity * t * pulse;
      });

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    frameId = requestAnimationFrame(animate);

    const handleResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(frameId);
      shieldGeometry.dispose();
      shieldMaterial.dispose();
      crossGeometry.dispose();
      crossMaterial.dispose();
      backShieldGeometry.dispose();
      backShieldMaterial.dispose();
      ringGeometry.dispose();
      ringMaterial.dispose();
      glowSprites.forEach(({ material }) => material.dispose());
      glowTexture.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} className="login-scene" aria-hidden="true" />;
}

export default LoginScene;
