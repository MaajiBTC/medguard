import { useCallback, useState } from 'react';

import { getContextualCapture, setTargetPatient as postTargetPatient } from '../../api/captures';

/**
 * Thin state wrapper around the Contextual capture debug/target-patient endpoints.
 * Login-time fields (on_duty_at_login, ward_assignment_at_login, device/network via
 * the related session) are already set server-side at login -- this hook only
 * needs to fetch them and expose setTargetPatient() for CaptureDevPanel.
 */
function useContextualCapture() {
  const [capture, setCapture] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getContextualCapture();
      setCapture(data);
      return data;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const setTargetPatient = useCallback(async (patientId) => {
    setLoading(true);
    setError(null);
    try {
      const data = await postTargetPatient(patientId);
      setCapture(data);
      return data;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { capture, loading, error, refresh, setTargetPatient };
}

export { useContextualCapture };
