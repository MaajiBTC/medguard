import { useEffect, useRef } from 'react';
import * as THREE from 'three';

import { CLINICAL_ROLES } from '../roles';

// CLAUDE.md scopes three.js to exactly two places: this panel (replacing the
// earlier spiral) and the login page. Hand-rolled with three.js primitives
// rather than a charting library -- this project has never pulled one in
// (frontend/package.json has no d3/recharts/chart.js), matching how every
// other visual here (icons, the login shield) is built from scratch.

// Same 4 severity colors already used elsewhere on this page (the live-feed
// table's row coloring) -- STANDARD_ACCESS excluded, matching the page's own
// default filter.
const SEVERITY_COLOR = {
  AUDITED_DEVIATION: 0xfbbf24,
  REDUCED_ACCESS: 0xfb923c,
  ACCESS_DENIED: 0xf87171,
  EMERGENCY_OVERRIDE: 0xe879f9,
};

const SEVERITY_LABEL = {
  AUDITED_DEVIATION: 'Audited deviation',
  REDUCED_ACCESS: 'Reduced access',
  ACCESS_DENIED: 'Access denied',
  EMERGENCY_OVERRIDE: 'Emergency override',
};

const EVENT_TYPES = Object.keys(SEVERITY_COLOR);

// Fixed row order for the role bar chart -- mirrors backend/staff/models.py's
// Staff.CLINICAL_ROLES, same set already used elsewhere on the frontend.
const ROLES = [...CLINICAL_ROLES];
const PLUM = 0x6528d9;

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function toHex(n) {
  return `#${n.toString(16).padStart(6, '0')}`;
}

// Same easing already used for the login shield's entrance (LoginScene.jsx).
function easeOutBack(x) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2;
}

function entriesSignature(entries) {
  return entries.map((e) => e.sequence).join(',');
}

function Legend() {
  return (
    <div className="ledger-chart-legend">
      {EVENT_TYPES.map((type) => (
        <span key={type} className="ledger-chart-legend-item">
          <span className="ledger-chart-legend-dot" style={{ background: toHex(SEVERITY_COLOR[type]) }} />
          {SEVERITY_LABEL[type]}
        </span>
      ))}
    </div>
  );
}

// The bar chart's bars are all one color (role isn't a severity), so its
// legend reads exact counts per role instead of explaining a color per item.
function RoleCounts({ entries }) {
  return (
    <div className="ledger-chart-legend">
      {ROLES.map((role) => (
        <span key={role} className="ledger-chart-legend-item">
          <span className="ledger-chart-legend-dot" style={{ background: toHex(PLUM) }} />
          {formatRole(role)}: {entries.filter((e) => e.staff_role === role).length}
        </span>
      ))}
    </div>
  );
}

/** Shared three.js mount/resize/dispose skeleton -- kept inline in each
 * component below rather than factored into a hook, matching how this
 * project's other two scenes (LoginScene.jsx, the outgoing
 * LedgerVisualization.jsx) have always been self-contained. `onFrame(elapsed)`
 * runs every animation frame; `stateRef.current.group` is where callers add
 * their chart geometry. */
function useThreeMount(mountRef, stateRef, onFrame) {
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const width = mount.clientWidth;
    const height = mount.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);

    const ambient = new THREE.AmbientLight(0xffffff, 0.7);
    const point = new THREE.PointLight(0xffffff, 1.1);
    point.position.set(3, 5, 4);
    scene.add(ambient, point);

    stateRef.current = {
      scene, camera, renderer, group, mount,
      entrance: { phase: 'in', start: performance.now() },
      everLoaded: false,
      lastSignature: null,
    };

    let frameId;
    const animate = () => {
      onFrame(stateRef.current, performance.now());
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

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
      group.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) obj.material.dispose();
      });
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      stateRef.current = null;
    };
    // Mount/unmount once only -- mountRef/stateRef are stable ref objects, and
    // onFrame is a fresh closure every render but doesn't capture any props/
    // state that change (it only reads the `state` object passed to it at
    // call time), so re-running this on every onFrame identity change would
    // just tear down and rebuild the whole scene for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

const BAR_ROW_SPACING = 0.55;
const BAR_HEIGHT = 0.34;
const BAR_MAX_LENGTH = 4;

/** Left card: a live 3D horizontal bar chart -- one extruded bar per staff
 * role (Doctor/Nurse/Pharmacist/Lab Technician/Clerk), length proportional to
 * how many current Ledger entries involved that role. Grows out from the
 * axis on first load / when new data arrives. Bars are a single on-brand
 * plum tone rather than the severity palette -- role isn't a severity, so
 * that color scheme wouldn't mean anything here; severity stays where it
 * still applies (the donut, the live-feed table rows). */
function LedgerRoleBarChart3D({ entries }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);

  const onFrame = (state) => {
    if (!state) return;
    const { group, entrance } = state;
    const elapsed = performance.now() - entrance.start;

    if (entrance.phase === 'in') {
      const t = Math.min(elapsed / 700, 1);
      group.scale.x = Math.max(easeOutBack(t), 0);
      if (t >= 1) {
        group.scale.x = 1;
        entrance.phase = 'idle';
      }
    } else if (entrance.phase === 'pulse') {
      const t = Math.min(elapsed / 380, 1);
      group.scale.x = 1 - 0.15 * Math.sin(Math.PI * t);
      if (t >= 1) {
        group.scale.x = 1;
        entrance.phase = 'idle';
      }
    }

    group.rotation.y += 0.0015;
  };

  useThreeMount(mountRef, stateRef, onFrame);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const { group, camera } = state;

    camera.position.set(3.5, 2, 6.5);
    camera.lookAt(1.5, -(BAR_ROW_SPACING * (ROLES.length - 1)) / 2, 0);

    group.children.forEach((mesh) => {
      mesh.geometry.dispose();
      mesh.material.dispose();
    });
    group.clear();

    const counts = ROLES.map((role) => entries.filter((e) => e.staff_role === role).length);
    const maxCount = Math.max(...counts, 1);

    ROLES.forEach((role, index) => {
      const length = Math.max((counts[index] / maxCount) * BAR_MAX_LENGTH, 0.06);
      const shape = new THREE.Shape();
      shape.moveTo(0, 0);
      shape.lineTo(length, 0);
      shape.lineTo(length, BAR_HEIGHT);
      shape.lineTo(0, BAR_HEIGHT);
      shape.closePath();

      const geometry = new THREE.ExtrudeGeometry(shape, { depth: 0.34, bevelEnabled: false });
      const material = new THREE.MeshStandardMaterial({
        color: PLUM,
        emissive: PLUM,
        emissiveIntensity: 0.4,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(0, -index * BAR_ROW_SPACING, 0);
      group.add(mesh);
    });

    const signature = entriesSignature(entries);
    if (!state.everLoaded) {
      state.everLoaded = true;
    } else if (signature !== state.lastSignature) {
      state.entrance.phase = 'pulse';
      state.entrance.start = performance.now();
    }
    state.lastSignature = signature;
  }, [entries]);

  return (
    <div>
      <div ref={mountRef} className="ledger-chart-mount" />
      <RoleCounts entries={entries} />
    </div>
  );
}

/** Right card: a live 3D donut -- one extruded annulus segment per event
 * type, sized by its share of the current feed. Pops in (uniform scale) on
 * first load / when new data arrives, same as the area chart's rise-in. */
function LedgerDonutChart3D({ entries }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);

  const onFrame = (state) => {
    if (!state) return;
    const { group, entrance } = state;
    const elapsed = performance.now() - entrance.start;

    if (entrance.phase === 'in') {
      const t = Math.min(elapsed / 700, 1);
      const s = Math.max(easeOutBack(t), 0);
      group.scale.setScalar(s);
      if (t >= 1) {
        group.scale.setScalar(1);
        entrance.phase = 'idle';
      }
    } else if (entrance.phase === 'pulse') {
      const t = Math.min(elapsed / 380, 1);
      group.scale.setScalar(1 - 0.12 * Math.sin(Math.PI * t));
      if (t >= 1) {
        group.scale.setScalar(1);
        entrance.phase = 'idle';
      }
    }

    group.rotation.z += 0.0015;
  };

  useThreeMount(mountRef, stateRef, onFrame);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const { group, camera } = state;

    camera.position.set(0, 3.2, 5.5);
    camera.lookAt(0, 0, 0);
    group.rotation.x = -0.5;

    group.children.forEach((mesh) => {
      mesh.geometry.dispose();
      mesh.material.dispose();
    });
    group.clear();

    const counts = {};
    let total = 0;
    EVENT_TYPES.forEach((type) => {
      counts[type] = entries.filter((e) => e.event_type === type).length;
      total += counts[type];
    });

    const OUTER_R = 1.7;
    const INNER_R = 0.9;

    if (total > 0) {
      let angle = -Math.PI / 2;
      EVENT_TYPES.forEach((type) => {
        const count = counts[type];
        if (count === 0) return;
        const sweep = (count / total) * Math.PI * 2;
        const start = angle;
        const end = angle + Math.max(sweep - 0.03, 0.02); // small gap between slices
        angle += sweep;

        const shape = new THREE.Shape();
        shape.moveTo(Math.cos(start) * OUTER_R, Math.sin(start) * OUTER_R);
        shape.absarc(0, 0, OUTER_R, start, end, false);
        shape.lineTo(Math.cos(end) * INNER_R, Math.sin(end) * INNER_R);
        shape.absarc(0, 0, INNER_R, end, start, true);
        shape.closePath();

        const geometry = new THREE.ExtrudeGeometry(shape, { depth: 0.6, bevelEnabled: false });
        // emissive keeps the true severity color visible under lighting, same
        // reasoning as the area chart's ribbons above.
        const material = new THREE.MeshStandardMaterial({
          color: SEVERITY_COLOR[type],
          emissive: SEVERITY_COLOR[type],
          emissiveIntensity: 0.45,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.z = -0.3;
        group.add(mesh);
      });
    } else {
      const ringGeometry = new THREE.RingGeometry(INNER_R, OUTER_R, 48);
      const ringMaterial = new THREE.MeshBasicMaterial({
        color: 0xc4b5fd, transparent: true, opacity: 0.4, side: THREE.DoubleSide,
      });
      group.add(new THREE.Mesh(ringGeometry, ringMaterial));
    }

    const signature = entriesSignature(entries);
    if (!state.everLoaded) {
      state.everLoaded = true;
    } else if (signature !== state.lastSignature) {
      state.entrance.phase = 'pulse';
      state.entrance.start = performance.now();
    }
    state.lastSignature = signature;
  }, [entries]);

  return (
    <div>
      <div ref={mountRef} className="ledger-chart-mount" />
      <Legend />
    </div>
  );
}

export { LedgerRoleBarChart3D, LedgerDonutChart3D };
