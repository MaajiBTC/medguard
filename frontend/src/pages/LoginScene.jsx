import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

// CLAUDE.md scopes three.js to exactly two places: this login/landing page and the
// Security Dashboard visualization (LedgerVisualization.jsx). Purely decorative --
// the actual login form is plain HTML/React; this is just the animated brand shield
// beside it. A plum shield body with a Rod of Asclepius emblem on its front face and a
// smaller shield emblem on its back -- both revealed during the 360-degree entrance spin.

const PLUM = 0x6528d9;
const WHITE = 0xffffff;

// Rod of Asclepius: a staff with a single snake coiled around it, head raised
// near the top -- built from primitive geometries (cylinder rod, helical tube
// for the snake's body, cone for its head) merged into one mesh so it behaves
// like the flat emblems elsewhere in this file (one geometry/material, scaled
// and positioned as a single unit).
function buildRodOfAsclepiusGeometry() {
  const rod = new THREE.CylinderGeometry(0.05, 0.05, 1.3, 12);

  const coilRadius = 0.17;
  const coilTurns = 2.25;
  const coilBottom = -0.55;
  const coilTop = 0.45;
  const coilPoints = [];
  const COIL_SAMPLES = 48;
  for (let i = 0; i <= COIL_SAMPLES; i += 1) {
    const t = i / COIL_SAMPLES;
    const angle = Math.PI * 2 * coilTurns * t;
    coilPoints.push(
      new THREE.Vector3(
        Math.cos(angle) * coilRadius,
        coilBottom + (coilTop - coilBottom) * t,
        Math.sin(angle) * coilRadius
      )
    );
  }
  const coil = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(coilPoints), 120, 0.065, 8, false);

  // Head sits where the coil ends, raised a little further up past the rod.
  const headAngle = Math.PI * 2 * coilTurns;
  const head = new THREE.ConeGeometry(0.12, 0.28, 10);
  head.translate(Math.cos(headAngle) * coilRadius * 1.1, coilTop + 0.16, Math.sin(headAngle) * coilRadius * 1.1);

  return mergeGeometries([rod, coil, head]);
}

// Classic clean shield silhouette: a pointed apex at top-center, curving
// outward to the widest point at the shoulders, then tapering back inward in
// one smooth curve to a point at the bottom -- all curves, no straight edges.
function buildShieldShape() {
  const shape = new THREE.Shape();
  shape.moveTo(0, 1.05);
  shape.bezierCurveTo(0.05, 0.95, 0.3, 0.8, 0.9, 0.65);
  shape.bezierCurveTo(0.95, 0.0, 0.55, -0.85, 0, -1.05);
  shape.bezierCurveTo(-0.55, -0.85, -0.95, 0.0, -0.9, 0.65);
  shape.bezierCurveTo(-0.3, 0.8, -0.05, 0.95, 0, 1.05);
  return shape;
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
const ROTATION_MS = ENTRANCE_MS * 2; // half the angular speed of the entrance spin
const SHIELD_DEPTH = 0.28;
const EMBLEM_DEPTH = 0.24;
const TARGET_SCALE = 1.5; // overall logo size, 50% bigger than the original 1.0
const POP_SCALE = 0.75; // rod/back-shield pop-up (z-offset from the shield body), 25% less

/** Animated shield for the login page's brand panel: a plum shield body that spins a
 * full 360 degrees while popping in (overshoot ease on scale, decelerating spin on
 * rotation), revealing the Rod of Asclepius on its front and a shield emblem on its
 * back before settling to a stop facing forward (rod side). Idles with a gentle
 * sway + bob afterward. Respects prefers-reduced-motion (renders the settled
 * shield, front-facing, with no spin). */
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

    // Synthetic "studio" environment (no HDR file needed) so the metal materials
    // below have something colorful to reflect everywhere, not just at the
    // direct-light highlight spots. Assigned explicitly per-material (envMap) --
    // not via scene.environment, which would silently apply it to anything else
    // added to the scene later too.
    const pmremGenerator = new THREE.PMREMGenerator(renderer);
    const envMap = pmremGenerator.fromScene(new RoomEnvironment(), 0.04).texture;

    const medallion = new THREE.Group();
    scene.add(medallion);

    // Body: the shield silhouette itself, not a separate coin.
    const shieldGeometry = new THREE.ExtrudeGeometry(buildShieldShape(), {
      depth: SHIELD_DEPTH,
      bevelEnabled: true,
      bevelThickness: 0.06,
      bevelSize: 0.05,
      bevelSegments: 4,
      curveSegments: 24,
    });
    shieldGeometry.center();
    // High metalness + low roughness for a brushed-steel look; emissive black so
    // it never glows (relies entirely on scene lights for its highlight/shading).
    const shieldMaterial = new THREE.MeshStandardMaterial({
      color: WHITE,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
    });
    const shield = new THREE.Mesh(shieldGeometry, shieldMaterial);
    shield.scale.set(0.8, 0.8, 1); // 20% smaller
    medallion.add(shield);

    // Front face: a Rod of Asclepius emblem, sitting proud of the shield.
    const rodGeometry = buildRodOfAsclepiusGeometry();
    // Same metal treatment as the shield body (color/metalness/roughness/envMap),
    // just plum instead of white.
    const rodMaterial = new THREE.MeshStandardMaterial({
      color: PLUM,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
    });
    const rod = new THREE.Mesh(rodGeometry, rodMaterial);
    const ROD_SCALE = 0.55; // 10% bigger than the previous cross's 0.5
    rod.scale.setScalar(ROD_SCALE);
    // Unlike the flat cross this replaced, the coil has real depth of its own
    // (it wraps all the way around the rod), so a flat POP_SCALE offset isn't
    // enough to clear the shield's front face -- most of the coil would render
    // embedded inside the solid shield mesh. Push it out by the geometry's own
    // half-depth (from its bounding box) plus a small visible gap instead.
    rodGeometry.computeBoundingBox();
    const rodBackZ = rodGeometry.boundingBox.min.z * ROD_SCALE;
    rod.position.z = SHIELD_DEPTH / 2 - rodBackZ + 0.02;
    medallion.add(rod);

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
    const backShieldMaterial = new THREE.MeshStandardMaterial({
      color: PLUM,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
    });
    const backShield = new THREE.Mesh(backShieldGeometry, backShieldMaterial);
    backShield.scale.set(0.341, 0.341, 1); // 0.31 base, 10% bigger
    backShield.position.z = -(SHIELD_DEPTH / 2 + EMBLEM_DEPTH / 2) * POP_SCALE; // pop-up reduced 25%
    medallion.add(backShield);

    medallion.scale.setScalar(reduceMotion ? TARGET_SCALE : 0.001);
    medallion.rotation.y = reduceMotion ? 0 : -Math.PI * 2;

    // Lavender key light for extra shading/depth on the rod/back-shield's own
    // emissive glow -- the shield body is unlit now, so these don't affect it.
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
        renderer.render(scene, camera);
        return;
      }

      const elapsed = now - start;
      const t = Math.min(elapsed / ENTRANCE_MS, 1);
      const scaleEased = easeOutBack(t);
      medallion.scale.setScalar(Math.max(scaleEased, 0.001) * TARGET_SCALE);

      const rt = Math.min(elapsed / ROTATION_MS, 1);
      if (rt < 1) {
        // One full 360-degree turn, decelerating to a stop facing forward (cross-side).
        medallion.rotation.y = -Math.PI * 2 * (1 - easeOutCubic(rt));
      } else {
        const idleElapsed = elapsed - ROTATION_MS;
        medallion.rotation.y = Math.sin(idleElapsed / 1800) * 0.12;
      }
      medallion.position.y = Math.sin(elapsed / 1400) * 0.06;

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
      rodGeometry.dispose();
      rodMaterial.dispose();
      backShieldGeometry.dispose();
      backShieldMaterial.dispose();
      envMap.dispose();
      pmremGenerator.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} className="login-scene" aria-hidden="true" />;
}

export default LoginScene;
