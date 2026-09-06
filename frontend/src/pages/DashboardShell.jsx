import { platformAuthenticatorIsAvailable, startRegistration } from '@simplewebauthn/browser';
import { useEffect, useState } from 'react';

import {
  approveDevice,
  changePassword,
  getCurrentSession,
  getPendingDeviceCount,
  getWebAuthnRegistrationOptions,
  listDevices,
  registerWebAuthnCredential,
  rejectDevice,
  removeDevice,
  removeProfilePhoto,
  uploadProfilePhoto,
} from '../api/auth';
import { CLINICAL_ROLES } from '../roles';
import RoleAvatar from './RoleAvatar';

const PENDING_DEVICE_POLL_MS = 25000;

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

function AlertIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
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

export { SearchIcon, StaffIcon, PatientsIcon, LedgerIcon, OverviewIcon, DisasterIcon, AlertIcon };

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function timeAgo(isoString) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes === 1) return '1 minute ago';
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
}

const PASSWORD_INITIAL = { current: '', next: '', confirm: '' };

/** Collapsible "Devices" section on the Profile page (clinical roles only -- see
 * CLINICAL_ROLES) -- one device per account (added 2026-08-30): pending requests
 * from unapproved devices can be accepted or declined here, and any non-primary
 * approved device can be removed (the primary device never gets a Remove button;
 * the backend enforces that too, see access.views.DeviceRemoveView). Starts
 * collapsed, per the user, and only fetches once first expanded. */
function DevicesPanel() {
  const [devices, setDevices] = useState(null);
  const [pendingRequests, setPendingRequests] = useState(null);
  const [error, setError] = useState(null);
  const [actioningId, setActioningId] = useState(null);

  const fetchDevices = async () => {
    setError(null);
    try {
      const data = await listDevices();
      setDevices(data.devices);
      setPendingRequests(data.pending_requests);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleToggle = (event) => {
    if (event.target.open && devices === null) {
      fetchDevices();
    }
  };

  const runAction = async (id, action) => {
    setActioningId(id);
    try {
      await action(id);
      await fetchDevices();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActioningId(null);
    }
  };

  return (
    <details className="detail-block" onToggle={handleToggle}>
      <summary>Devices</summary>

      {error && <p role="alert" className="dev-error">{error}</p>}
      {devices === null && !error && <p className="meta-line">Loading…</p>}

      {pendingRequests && pendingRequests.length > 0 && (
        <div>
          <h4>Pending requests</h4>
          {pendingRequests.map((req) => (
            <div className="card-row" key={req.id}>
              <div className="card-row-main">
                <span className="name-line">{req.device_type || 'Unknown device'}</span>
                <span className="meta-line">
                  {req.user_agent || 'No device details'} · requested {timeAgo(req.requested_at)}
                </span>
              </div>
              <div className="card-row-actions">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={actioningId === req.id}
                  onClick={() => runAction(req.id, approveDevice)}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={actioningId === req.id}
                  onClick={() => runAction(req.id, rejectDevice)}
                >
                  Decline
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {devices && devices.length > 0 && (
        <div>
          <h4>Approved devices</h4>
          {devices.map((device) => (
            <div className="card-row" key={device.id}>
              <div className="card-row-main">
                <span className="name-line">
                  {device.device_type || 'Unknown device'}
                  {device.is_primary && <span className="badge badge-active">Primary</span>}
                </span>
                <span className="meta-line">{device.user_agent || 'No device details'}</span>
              </div>
              {!device.is_primary && (
                <div className="card-row-actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={actioningId === device.id}
                    onClick={() => runAction(device.id, removeDevice)}
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {devices && devices.length === 0 && pendingRequests && pendingRequests.length === 0 && (
        <p className="meta-line">No devices on this account yet.</p>
      )}
    </details>
  );
}

/** Collapsible "Step-up verification" section on the Profile page (clinical
 * roles only) -- added 2026-09-06, replacing a typed PIN the same day with
 * device biometrics. Self-service and per-device by nature: nobody but the
 * staff member, sitting at this device, can register its own Face ID/
 * fingerprint/Windows Hello -- that's inherent to how WebAuthn's security
 * model works, not a rule this app invents. `available` starts `null`
 * (checking) so the panel doesn't flash an incorrect state on mount. */
function StepUpEnrollmentPanel() {
  const [available, setAvailable] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    platformAuthenticatorIsAvailable().then(setAvailable).catch(() => setAvailable(false));
  }, []);

  const handleEnroll = async () => {
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const optionsJSON = await getWebAuthnRegistrationOptions();
      const credential = await startRegistration({ optionsJSON });
      await registerWebAuthnCredential(credential);
      setNotice('Step-up verification enabled on this device.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <details className="detail-block">
      <summary>Step-up verification</summary>
      {available === false && (
        <p className="meta-line">
          This device doesn't have a fingerprint reader, Face ID, or Windows Hello set
          up, so there's nothing to enroll here. If a session ever scores into the
          reduced-access band on this device, you can ask a logged-in colleague to
          verify instead.
        </p>
      )}
      {available && (
        <>
          <p className="meta-line">
            Enable your device's own fingerprint, Face ID, or Windows Hello as the
            second factor for reduced-access sessions (CLAUDE.md's 40–69% band). This
            is per device -- enroll again if you sign in somewhere new.
          </p>
          {error && <p role="alert" className="dev-error">{error}</p>}
          {notice && <p className="notice">{notice}</p>}
          <div className="button-row">
            <button type="button" className="btn-primary" disabled={submitting} onClick={handleEnroll}>
              {submitting ? 'Waiting for your device…' : 'Enable on this device'}
            </button>
          </div>
        </>
      )}
    </details>
  );
}

function ProfileField({ label, value }) {
  return (
    <p className="meta-line">
      <span className="detail-label">{label}:</span> {value}
    </p>
  );
}

/** Photo upload/preview/remove section on the left of the profile card --
 * added 2026-09-05, per the user, so the Security dashboard can show a real
 * photo instead of RoleAvatar's cartoon once one exists. Clicking the avatar
 * itself opens the file picker (no separate "Upload photo" button, per the
 * user) -- a "Remove photo" text link sits underneath once one exists.
 * `photoUrl`/`onPhotoChange` are lifted to ProfilePanel so the rest of the
 * card (and the header's own avatar use, if any) stays in sync after an
 * upload/removal. */
function ProfilePhotoSection({ role, photoUrl, onPhotoChange }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleFileChange = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const data = await uploadProfilePhoto(file);
      onPhotoChange(data.photo_url);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async () => {
    setError(null);
    setBusy(true);
    try {
      await removeProfilePhoto();
      onPhotoChange(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="profile-detail-photo">
      <label
        className={`profile-avatar-upload${busy ? ' profile-avatar-upload-busy' : ''}`}
        title={photoUrl ? 'Click to change photo' : 'Click to upload a photo'}
      >
        <RoleAvatar role={role} photoUrl={photoUrl} />
        <input
          type="file"
          accept="image/*"
          onChange={handleFileChange}
          disabled={busy}
          hidden
        />
      </label>
      {photoUrl && (
        <button type="button" className="link-button" disabled={busy} onClick={handleRemove}>
          Remove photo
        </button>
      )}
      {error && <p role="alert" className="dev-error">{error}</p>}
    </div>
  );
}

/** The page a click on the header's profile icon opens, from any dashboard: the
 * caller's own labeled details (name, staff ID, role, and -- for clinical roles
 * -- live duty/ward/on-call status), a profile photo upload, and a
 * change-password form (password only -- nothing else here is editable).
 * Duty/ward/on-call come from getCurrentSession() (live, not the `staff` prop's
 * login-time snapshot) so the card reflects an admin toggling this staff
 * member's status elsewhere without needing a fresh login. */
function ProfilePanel({ staff, onBack }) {
  const [password, setPassword] = useState(PASSWORD_INITIAL);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [session, setSession] = useState(null);

  useEffect(() => {
    getCurrentSession().then(setSession).catch(() => {});
  }, []);

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

  const isClinical = CLINICAL_ROLES.has(staff.role);
  const dutyLabel = session
    ? `${session.on_duty ? 'On duty' : 'Off duty'}${session.ward ? ` (${session.ward})` : ''}`
    : '…';

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}>
        ← Back
      </button>

      <div className="panel-card">
        <h2>My profile</h2>
        <div className="profile-detail-row">
          <ProfilePhotoSection
            role={staff.role}
            photoUrl={session ? session.photo_url : null}
            onPhotoChange={(photo_url) => setSession((s) => (s ? { ...s, photo_url } : s))}
          />
          <div className="profile-detail-fields">
            <ProfileField label="Name" value={staff.full_name} />
            <ProfileField label="Staff ID" value={staff.staff_id} />
            <ProfileField label="Role" value={formatRole(staff.role)} />
            {isClinical && <ProfileField label="Duty status" value={dutyLabel} />}
            {isClinical && <ProfileField label="On call" value={session ? (session.on_call ? 'Yes' : 'No') : '…'} />}
          </div>
        </div>
      </div>

      {isClinical && <DevicesPanel />}

      {isClinical && <StepUpEnrollmentPanel />}

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
  const [hasPendingDevices, setHasPendingDevices] = useState(false);

  // Pending-device badge (added 2026-08-30) -- polled only for clinical roles,
  // since admin/security_officer are shared accounts that never get Device rows
  // at all (see Staff.NO_WARD_DUTY_ROLES) and so can never have a pending request.
  useEffect(() => {
    if (!staff || !CLINICAL_ROLES.has(staff.role)) return undefined;

    let cancelled = false;
    const poll = async () => {
      try {
        const data = await getPendingDeviceCount();
        if (!cancelled) setHasPendingDevices(data.count > 0);
      } catch {
        // Best-effort badge -- a failed poll just leaves the last known state.
      }
    };
    poll();
    const intervalId = setInterval(poll, PENDING_DEVICE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [staff]);

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
                {/* Optional red count pill (added 2026-09-06 for unacknowledged
                    security alerts) -- same "something needs you" language as
                    the header's .profile-badge-dot. */}
                {item.badgeCount > 0 && <span className="nav-badge">{item.badgeCount}</span>}
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
              {hasPendingDevices && <span className="profile-badge-dot" aria-hidden="true" />}
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
