// A real, plain-SVG donut chart -- added 2026-09-18 for the Admin
// dashboard's Staff/Patients panels. Deliberately NOT three.js: CLAUDE.md
// scopes three.js to exactly two places (the Security Dashboard's own
// LedgerDonutChart3D, and the login page) and keeps every other screen
// plain React for clarity/performance -- confirmed with the user via
// AskUserQuestion rather than assumed, since it would have been easy to
// just copy the Security donut's look without noticing that rule.
//
// Generic over `rows: [{key, label, count, color}]`, same shape
// LedgerCharts3D.jsx's HorizontalBarChart already uses, so callers can
// reuse one `rows` array to feed both a bar and a donut of the same data.

const SIZE = 160;
const STROKE = 22;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function DonutChart2D({ rows }) {
  const total = rows.reduce((sum, r) => sum + r.count, 0);

  const segments = rows
    .filter((r) => r.count > 0)
    .reduce((acc, r) => {
      const fraction = total > 0 ? r.count / total : 0;
      const length = fraction * CIRCUMFERENCE;
      const offset = acc.length ? acc[acc.length - 1].offset + acc[acc.length - 1].length : 0;
      acc.push({ ...r, length, offset });
      return acc;
    }, []);

  return (
    <div className="donut-chart-row">
      <div className="ledger-chart-legend">
        {rows.map((r) => (
          <span key={r.key} className="ledger-chart-legend-item">
            <span className="ledger-chart-legend-dot" style={{ background: r.color }} />
            {r.label} ({r.count})
          </span>
        ))}
      </div>
      <div className="ledger-chart-mount" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth={STROKE}
          />
          {total === 0 && (
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke="var(--lavender)"
              strokeWidth={STROKE}
            />
          )}
          {segments.map((s) => (
            <circle
              key={s.key}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={s.color}
              strokeWidth={STROKE}
              strokeDasharray={`${s.length} ${CIRCUMFERENCE - s.length}`}
              strokeDashoffset={-s.offset}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
              strokeLinecap={segments.length === 1 ? 'butt' : 'round'}
            />
          ))}
          <text
            x={SIZE / 2}
            y={SIZE / 2}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize="1.5rem"
            fontWeight="700"
            fill="var(--plum-deep)"
          >
            {total}
          </text>
        </svg>
      </div>
    </div>
  );
}

export default DonutChart2D;
