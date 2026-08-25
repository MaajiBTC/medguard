import { useEffect, useRef } from 'react';
import * as THREE from 'three';

// CLAUDE.md scopes three.js to exactly two places: this panel and the login page.
// This is a live visual layer on top of the Security Dashboard's real table --
// filtering/drill-down stays in plain React/HTML there; this only shows severity and
// recency at a glance.

const SEVERITY_COLOR = {
  STANDARD_ACCESS: 0x4ade80,
  AUDITED_DEVIATION: 0xfbbf24,
  REDUCED_ACCESS: 0xfb923c,
  ACCESS_DENIED: 0xf87171,
  EMERGENCY_OVERRIDE: 0xe879f9,
};

const RING_RADIUS = 3.2;
const MAX_MARKERS = 30;

/** Recent ledger entries as color-coded markers orbiting a ring, newest brightest.
 * Purely a visualization -- entries prop drives what's shown, no data fetching here. */
function LedgerVisualization({ entries }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const width = mount.clientWidth;
    const height = mount.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
    camera.position.set(0, 3.5, 7);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(RING_RADIUS, 0.015, 8, 96),
      new THREE.MeshBasicMaterial({ color: 0x4b4b57, transparent: true, opacity: 0.5 })
    );
    ring.rotation.x = Math.PI / 2;
    scene.add(ring);

    const markerGroup = new THREE.Group();
    scene.add(markerGroup);

    let frameId;
    const animate = () => {
      markerGroup.rotation.y += 0.0025;
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    stateRef.current = { scene, camera, renderer, markerGroup, mount };

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
      markerGroup.children.forEach((mesh) => {
        mesh.geometry.dispose();
        mesh.material.dispose();
      });
      ring.geometry.dispose();
      ring.material.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const { markerGroup } = state;

    markerGroup.children.forEach((mesh) => {
      mesh.geometry.dispose();
      mesh.material.dispose();
    });
    markerGroup.clear();

    const recent = entries.slice(0, MAX_MARKERS);
    recent.forEach((entry, index) => {
      const angle = (index / MAX_MARKERS) * Math.PI * 2;
      const recency = 1 - index / Math.max(recent.length, 1);
      const color = SEVERITY_COLOR[entry.event_type] ?? 0x8888aa;

      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.09 + recency * 0.09, 16, 16),
        new THREE.MeshStandardMaterial({
          color,
          emissive: color,
          emissiveIntensity: 0.3 + recency * 0.7,
        })
      );
      mesh.position.set(Math.cos(angle) * RING_RADIUS, 0, Math.sin(angle) * RING_RADIUS);
      markerGroup.add(mesh);
    });

    if (!markerGroup.userData.lit) {
      const ambient = new THREE.AmbientLight(0xffffff, 0.6);
      const point = new THREE.PointLight(0xffffff, 1.2);
      point.position.set(2, 4, 4);
      state.scene.add(ambient, point);
      markerGroup.userData.lit = true;
    }
  }, [entries]);

  return <div ref={mountRef} className="ledger-visualization" />;
}

export default LedgerVisualization;
