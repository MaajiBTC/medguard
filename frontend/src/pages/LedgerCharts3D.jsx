import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

import { CLINICAL_ROLES } from '../roles';

// CLAUDE.md scopes three.js to exactly two places: this panel (replacing the
// earlier spiral) and the login page. LedgerDonutChart3D below is still
// hand-rolled three.js (no charting library -- frontend/package.json has no
// d3/recharts/chart.js -- matching how every other visual here is built from
// scratch); LedgerRoleBarChart is plain 2D CSS, per the user (2026-08-31).

// Exact severity palette per the user (2026-08-31) -- same 5 colors used for
// the live-feed table's row stripes (App.css's .ledger-row.severity-* rules).
// STANDARD_ACCESS is included here (and so in EVENT_TYPES/the donut below)
// since it's no longer hidden from the feed by default.
const SEVERITY_COLOR = {
  STANDARD_ACCESS: 0x00cc00,
  AUDITED_DEVIATION: 0xffff00,
  REDUCED_ACCESS: 0xff9300,
  ACCESS_DENIED: 0xff0000,
  EMERGENCY_OVERRIDE: 0x0000ff,
};

const SEVERITY_LABEL = {
  STANDARD_ACCESS: 'Standard access',
  AUDITED_DEVIATION: 'Audited deviation',
  REDUCED_ACCESS: 'Reduced access',
  ACCESS_DENIED: 'Access denied',
  EMERGENCY_OVERRIDE: 'Emergency override',
};

const EVENT_TYPES = Object.keys(SEVERITY_COLOR);

// Fixed row order for the role bar chart -- mirrors backend/staff/models.py's
// Staff.CLINICAL_ROLES, same set already used elsewhere on the frontend.
const ROLES = [...CLINICAL_ROLES];

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function toHex(n) {
  return `#${n.toString(16).padStart(6, '0')}`;
}

// Heat scale for the role bar chart, per the user: green (least activity) ->
// yellow -> orange -> red (most). t=0..1, where 1 is the busiest role in the
// current feed.
const HEAT_STOPS = [
  [34, 197, 94], // green
  [234, 179, 8], // yellow
  [249, 115, 22], // orange
  [239, 68, 68], // red
];

function heatColor(t) {
  const clamped = Math.min(Math.max(t, 0), 1);
  const scaled = clamped * (HEAT_STOPS.length - 1);
  const i = Math.min(Math.floor(scaled), HEAT_STOPS.length - 2);
  const localT = scaled - i;
  const [r1, g1, b1] = HEAT_STOPS[i];
  const [r2, g2, b2] = HEAT_STOPS[i + 1];
  const r = Math.round(r1 + (r2 - r1) * localT);
  const g = Math.round(g1 + (g2 - g1) * localT);
  const b = Math.round(b1 + (b2 - b1) * localT);
  return `rgb(${r}, ${g}, ${b})`;
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

/** Left card: a plain 2D horizontal bar chart (per the user -- no three.js
 * here, unlike the donut) -- one row per staff role (Doctor/Nurse/
 * Pharmacist/Lab Technician/Clerk), bar length proportional to how many
 * current Ledger entries involved that role. Bar color is a red/orange/
 * yellow/green heat scale keyed to that role's count relative to the busiest
 * role, not the severity palette -- role isn't a severity, so that scheme
 * wouldn't mean anything here; severity stays where it still applies (the
 * donut, the live-feed table rows). Bars animate in via a CSS width
 * transition, growing from 0 a tick after mount/data changes rather than
 * jumping straight to their final width. */
function LedgerRoleBarChart({ entries }) {
  const counts = ROLES.map((role) => entries.filter((e) => e.staff_role === role).length);
  const maxCount = Math.max(...counts, 1);
  const targetPercents = counts.map((c) => (c / maxCount) * 100);
  const targetKey = targetPercents.join(',');

  const [percents, setPercents] = useState(() => ROLES.map(() => 0));

  useEffect(() => {
    const frameId = requestAnimationFrame(() => setPercents(targetPercents));
    return () => cancelAnimationFrame(frameId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  return (
    <div className="role-bar-chart">
      {ROLES.map((role, index) => (
        <div className="role-bar-row" key={role}>
          <span className="role-bar-label">{formatRole(role)}</span>
          <div className="role-bar-track">
            <div
              className="role-bar-fill"
              style={{ width: `${percents[index]}%`, background: heatColor(counts[index] / maxCount) }}
            />
          </div>
          <span className="role-bar-count">{counts[index]}</span>
        </div>
      ))}
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

export { LedgerRoleBarChart, LedgerDonutChart3D };
