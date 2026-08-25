import { useCallback, useEffect, useState } from 'react';

import './App.css';
import { getCurrentSession, logout as apiLogout } from './api/auth';
import { getToken, setToken } from './api/client';
import { useBehavioralCapture } from './capture/behavioral/useBehavioralCapture';
import CaptureDevPanel from './pages/CaptureDevPanel';
import LoginPage from './pages/LoginPage';

/**
 * The authenticated app shell. useBehavioralCapture is mounted HERE, and only
 * here -- never on LoginPage -- per CLAUDE.md's security note (see
 * useBehavioralCapture.js and LoginPage.jsx for the full explanation). Unmounting
 * this component (e.g. on logout) runs the hook's cleanup, which detaches every
 * listener.
 */
function AuthenticatedShell({ initialStaff, onLoggedOut }) {
  const [staff, setStaff] = useState(initialStaff);
  const { flushNow } = useBehavioralCapture({ enabled: true });

  useEffect(() => {
    if (staff) return;
    // Page was refreshed with a token already in sessionStorage but no staff
    // details in memory -- recover them from the debug session-current endpoint.
    getCurrentSession()
      .then((data) =>
        setStaff({ staff_id: data.staff_id, full_name: data.staff_full_name, role: data.role })
      )
      .catch(() => {
        // Token is invalid/expired -- fall back to logged-out state.
        onLoggedOut();
      });
  }, [staff, onLoggedOut]);

  const handleLogout = useCallback(async () => {
    flushNow();
    try {
      await apiLogout();
    } finally {
      onLoggedOut();
    }
  }, [flushNow, onLoggedOut]);

  return <CaptureDevPanel staff={staff} onLogout={handleLogout} flushNow={flushNow} />;
}

function App() {
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()));
  const [loggedInStaff, setLoggedInStaff] = useState(null);

  const handleLoginSuccess = (data) => {
    setLoggedInStaff(data.staff);
    setHasToken(true);
  };

  const handleLoggedOut = () => {
    setToken(null);
    setLoggedInStaff(null);
    setHasToken(false);
  };

  if (!hasToken) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  return <AuthenticatedShell initialStaff={loggedInStaff} onLoggedOut={handleLoggedOut} />;
}

export default App;
