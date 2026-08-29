import { useEffect, useRef } from 'react';
import * as THREE from 'three';

// CLAUDE.md scopes three.js to exactly two places: this login/landing page and the
// Security Dashboard visualization (LedgerVisualization.jsx). Purely decorative --
// the actual login form is plain HTML/React; this is just the animated brand shield
// beside it. A shield stands in for MedGuard's own identity (access control /
// protection), not a copy of any particular reference logo.

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

const ENTRANCE_MS = 1100;

/** Animated shield entrance for the login page's brand panel: scales/rotates in
 * with an overshoot ease, then settles into a gentle idle bob + orbiting ring.
 * Respects prefers-reduced-motion (renders the settled shield with no animation). */
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

    const geometry = new THREE.ExtrudeGeometry(buildShieldShape(), {
      depth: 0.28,
      bevelEnabled: true,
      bevelThickness: 0.06,
      bevelSize: 0.05,
      bevelSegments: 4,
      curveSegments: 24,
    });
    geometry.center();
    const material = new THREE.MeshStandardMaterial({
      color: 0x14b8a6,
      emissive: 0x0d9488,
      emissiveIntensity: 0.3,
      metalness: 0.4,
      roughness: 0.35,
    });
    const shield = new THREE.Mesh(geometry, material);
    shield.scale.setScalar(reduceMotion ? 1 : 0.001);
    shield.rotation.y = reduceMotion ? 0 : -1.1;
    scene.add(shield);

    const ringGeometry = new THREE.TorusGeometry(1.5, 0.012, 8, 96);
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: 0x5eead4,
      transparent: true,
      opacity: reduceMotion ? 0.5 : 0,
    });
    const ring = new THREE.Mesh(ringGeometry, ringMaterial);
    ring.rotation.x = Math.PI / 2.4;
    scene.add(ring);

    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    const key = new THREE.PointLight(0x5eead4, 1.4);
    key.position.set(2, 2, 3);
    const rim = new THREE.PointLight(0x2563eb, 0.8);
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
      const entranceT = Math.min(elapsed / ENTRANCE_MS, 1);
      const eased = easeOutBack(entranceT);
      shield.scale.setScalar(Math.max(eased, 0.001));
      shield.rotation.y = -1.1 * (1 - entranceT) + Math.sin(elapsed / 1800) * 0.15;
      shield.position.y = Math.sin(elapsed / 1400) * 0.06;
      ring.material.opacity = 0.5 * entranceT;
      ring.rotation.z += 0.0035;

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
      geometry.dispose();
      material.dispose();
      ringGeometry.dispose();
      ringMaterial.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} className="login-scene" aria-hidden="true" />;
}

export default LoginScene;
