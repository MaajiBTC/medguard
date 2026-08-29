// Small hand-rolled icon set (no icon library dependency) -- just enough to match
// the sidebar/search affordances the reference design uses.
function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

export { SearchIcon };

/** Shared layout for the three authenticated dashboards: a plum-deep left sidebar
 * (wordmark, role-scoped nav, logout) plus a main area (page title/subtitle + staff
 * identity, then a white card containing `children`). Uses the fixed light brand
 * palette (--plum/--plum-deep/--lavender/--off-white), same as the login page. */
function DashboardShell({ navItems, activeItem, onNavChange, staff, onLogout, title, subtitle, children }) {
  return (
    <div className="dashboard-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">MedGuard</div>

        {navItems && navItems.length > 0 && (
          <nav className="sidebar-nav">
            {navItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`sidebar-nav-item${activeItem === item.key ? ' active' : ''}`}
                onClick={() => onNavChange(item.key)}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>
        )}

        <button type="button" className="sidebar-logout" onClick={onLogout}>
          <LogoutIcon />
          Log out
        </button>
      </aside>

      <div className="dashboard-main">
        <header className="shell-header">
          <div>
            <h1>{title}</h1>
            {subtitle && <p className="shell-subtitle">{subtitle}</p>}
          </div>
          {staff && (
            <div className="shell-identity">
              <strong>{staff.full_name}</strong>
              <span>{staff.staff_id}</span>
            </div>
          )}
        </header>

        <div className="shell-content">{children}</div>
      </div>
    </div>
  );
}

export default DashboardShell;
