import { useState } from 'react';

import { changePassword } from '../api/auth';

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

function StaffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function PatientsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z" />
    </svg>
  );
}

function LedgerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
    </svg>
  );
}

function OverviewIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  );
}

function DisasterIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

// Static brand mark for the sticky header -- a flat shield+cross, echoing the
// login page's 3D shield without using three.js (CLAUDE.md scopes three.js to
// just the login page and the Security Dashboard visualization).
function BrandLogoIcon() {
  return (
    <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 2c2.2 1.6 4.6 2.4 7 2.4V11c0 5.2-3 8.8-7 10.6C8 19.8 5 16.2 5 11V4.4c2.4 0 4.8-.8 7-2.4Z"
        fill="#fff"
      />
      <path d="M12 7.5v9M7.5 12h9" stroke="var(--plum-deep)" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function ProfileIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
    </svg>
  );
}

export { SearchIcon, StaffIcon, PatientsIcon, LedgerIcon, OverviewIcon, DisasterIcon };

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

const PASSWORD_INITIAL = { current: '', next: '', confirm: '' };

/** The page a click on the header's profile icon opens, from any dashboard: the
 * caller's own read-only details plus a change-password form (password only --
 * nothing else here is editable). */
function ProfilePanel({ staff, onBack }) {
  const [password, setPassword] = useState(PASSWORD_INITIAL);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (password.next !== password.confirm) {
      setError('New password and confirmation do not match.');
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(password.current, password.next);
      setNotice('Password updated.');
      setPassword(PASSWORD_INITIAL);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}>
        ← Back
      </button>

      <div className="panel-card">
        <h2>My profile</h2>
        <p className="meta-line">{staff.full_name}</p>
        <p className="meta-line">{staff.staff_id} · {formatRole(staff.role)}</p>
      </div>

      <div className="panel-card">
        <h3>Change password</h3>
        <form onSubmit={handleSubmit}>
          <label className="form-label">
            Current password
            <input
              className="form-input"
              type="password"
              value={password.current}
              onChange={(e) => setPassword({ ...password, current: e.target.value })}
              required
            />
          </label>
          <label className="form-label">
            New password
            <input
              className="form-input"
              type="password"
              value={password.next}
              onChange={(e) => setPassword({ ...password, next: e.target.value })}
              required
              minLength={8}
            />
          </label>
          <label className="form-label">
            Confirm new password
            <input
              className="form-input"
              type="password"
              value={password.confirm}
              onChange={(e) => setPassword({ ...password, confirm: e.target.value })}
              required
              minLength={8}
            />
          </label>
          {error && <p role="alert" className="dev-error">{error}</p>}
          {notice && <p className="notice">{notice}</p>}
          <div className="button-row">
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Saving…' : 'Save password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Shared layout for the three authenticated dashboards (every page except the
 * login page): a sticky top header (hamburger menu + page label on the left,
 * enlarged MedGuard brand mark centered, profile icon on the right) plus a
 * plum-deep off-canvas nav drawer (wordmark, role-scoped nav, logout) toggled by
 * the header's hamburger button, closed by default -- the dashboard's own
 * content is what you see first, not the menu. The profile icon opens
 * ProfilePanel in place of `children`, independent of whatever page the calling
 * dashboard has active, so it works the same from all three. Uses the fixed
 * light brand palette (--plum/--plum-deep/--lavender/--off-white), same as the
 * login page. */
function DashboardShell({ navItems, activeItem, onNavChange, staff, onLogout, title, children }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  const selectNav = (key) => {
    onNavChange(key);
    setDrawerOpen(false);
  };

  return (
    <div className="dashboard-shell">
      {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} />}

      <aside className={`sidebar${drawerOpen ? ' open' : ''}`}>
        <div className="sidebar-brand">MedGuard</div>

        {navItems && navItems.length > 0 && (
          <nav className="sidebar-nav">
            {navItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`sidebar-nav-item${activeItem === item.key ? ' active' : ''}`}
                onClick={() => selectNav(item.key)}
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
          <div className="shell-header-page">
            <button
              type="button"
              className="menu-button"
              onClick={() => setDrawerOpen((open) => !open)}
              aria-label="Toggle navigation menu"
            >
              <MenuIcon />
            </button>
            <h1 className="shell-header-page-label">{title}</h1>
          </div>

          <div className="brand-mark">
            <BrandLogoIcon />
            <span>MedGuard</span>
          </div>

          {staff && (
            <button
              type="button"
              className="profile-button"
              onClick={() => setProfileOpen(true)}
              aria-label="View profile"
            >
              <ProfileIcon />
            </button>
          )}
        </header>

        <div className="shell-content">
          {profileOpen ? <ProfilePanel staff={staff} onBack={() => setProfileOpen(false)} /> : children}
        </div>
      </div>
    </div>
  );
}

export default DashboardShell;
