import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

// CLAUDE.md scopes three.js to exactly two places: this login/landing page and the
// Security Dashboard visualization (LedgerVisualization.jsx). Purely decorative --
// the actual login form is plain HTML/React; this is just the animated brand shield
// beside it. A plum shield body with a hospital cross emblem on its front face and a
// smaller shield emblem on its back -- both revealed during the 360-degree entrance spin.

const PLUM = 0x6528d9;
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

/** Animated shield for the login page's brand panel: a plum shield body that spins a
 * full 360 degrees while popping in (overshoot ease on scale, decelerating spin on
 * rotation), revealing the hospital cross on its front and a shield emblem on its
 * back before settling to a stop facing forward (cross side). Idles with a gentle
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
    // High metalness + low roughness for a brushed-steel look; emissive black so
    // it never glows (relies entirely on scene lights for its highlight/shading).
    const shieldMaterial = new THREE.MeshStandardMaterial({
      color: PLUM,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
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
    // Same metal treatment as the shield body (color/metalness/roughness/envMap),
    // just red instead of plum.
    const crossMaterial = new THREE.MeshStandardMaterial({
      color: WHITE,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
    });
    const cross = new THREE.Mesh(crossGeometry, crossMaterial);
    cross.position.z = SHIELD_DEPTH / 2;
    medallion.add(cross);

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
      color: WHITE,
      emissive: 0x000000,
      metalness: 0.9,
      roughness: 0.4,
      envMap,
      envMapIntensity: 0.75,
    });
    const backShield = new THREE.Mesh(backShieldGeometry, backShieldMaterial);
    backShield.scale.set(0.62, 0.62, 1);
    backShield.position.z = -(SHIELD_DEPTH / 2 + EMBLEM_DEPTH / 2);
    medallion.add(backShield);

    medallion.scale.setScalar(reduceMotion ? 1 : 0.001);
    medallion.rotation.y = reduceMotion ? 0 : -Math.PI * 2;

    // Lavender key light for extra shading/depth on the cross/back-shield's own
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
      medallion.scale.setScalar(Math.max(scaleEased, 0.001));

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
      crossGeometry.dispose();
      crossMaterial.dispose();
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
