import { useCallback, useEffect, useRef } from 'react';

import { postBehavioralEvents } from '../../api/captures';
import { createEventBuffer } from './eventBuffer';

const FLUSH_INTERVAL_MS = 3000;
const FLUSH_SIZE_THRESHOLD = 50;
const MOVE_SAMPLE_INTERVAL_MS = 15; // spec target: ~10-20ms sampling on movement

function now() {
  // High-resolution, monotonic -- what dwell/flight-time math will eventually want.
  return performance.now();
}

/**
 * Attaches keystroke/mouse/touch listeners and buffers raw, timestamped events,
 * flushing them to POST /api/captures/behavioral/events/ periodically.
 *
 * SECURITY: call this ONLY from inside the authenticated app shell, after login --
 * never from LoginPage or anywhere near the password field. Capturing keystroke
 * timing on a password field would store timing data that could effectively
 * reconstruct the typed password. See CLAUDE.md's Behavioral module security note.
 *
 * Per CLAUDE.md's capture spec: keydown/keyup/mousedown/mouseup are captured in
 * full (every event); mousemove/touchmove are throttled to ~15ms sampling since
 * raw mousemove fires far faster than that. This module only stores raw events --
 * no derived features, no matching/scoring (that's the Scoring Engine, step 2).
 *
 * @param {object} [options]
 * @param {boolean} [options.enabled] - set false to detach without unmounting.
 * @returns {{ flushNow: () => void }}
 */
function useBehavioralCapture({ enabled = true } = {}) {
  const bufferRef = useRef(createEventBuffer());
  const lastMouseMoveRef = useRef(0);
  const lastTouchMoveRef = useRef(0);

  const flush = useCallback(() => {
    const buffer = bufferRef.current;
    if (buffer.isEmpty()) return;
    const batch = buffer.drain();
    // Best-effort: capture is telemetry, never allowed to block or break the UI.
    postBehavioralEvents(batch).catch(() => {});
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    const buffer = bufferRef.current;

    const recordAndMaybeFlush = (push) => {
      push();
      if (buffer.size() >= FLUSH_SIZE_THRESHOLD) {
        flush();
      }
    };

    const handleKeydown = (e) => {
      recordAndMaybeFlush(() => buffer.pushKeystroke({ event: 'keydown', code: e.code, t: now() }));
    };
    const handleKeyup = (e) => {
      recordAndMaybeFlush(() => buffer.pushKeystroke({ event: 'keyup', code: e.code, t: now() }));
    };
    const handleMousedown = (e) => {
      recordAndMaybeFlush(() =>
        buffer.pushMouse({ event: 'mousedown', x: e.clientX, y: e.clientY, button: e.button, t: now() })
      );
    };
    const handleMouseup = (e) => {
      recordAndMaybeFlush(() =>
        buffer.pushMouse({ event: 'mouseup', x: e.clientX, y: e.clientY, button: e.button, t: now() })
      );
    };
    const handleMousemove = (e) => {
      const t = now();
      if (t - lastMouseMoveRef.current < MOVE_SAMPLE_INTERVAL_MS) return;
      lastMouseMoveRef.current = t;
      recordAndMaybeFlush(() => buffer.pushMouse({ event: 'mousemove', x: e.clientX, y: e.clientY, t }));
    };
    const pushTouches = (changedTouches, eventName, t) => {
      for (let i = 0; i < changedTouches.length; i += 1) {
        const touch = changedTouches[i];
        buffer.pushTouch({
          event: eventName,
          x: touch.clientX,
          y: touch.clientY,
          pressure: typeof touch.force === 'number' ? touch.force : undefined,
          contact_size: typeof touch.radiusX === 'number' ? touch.radiusX : undefined,
          touch_id: touch.identifier,
          t,
        });
      }
    };
    const handleTouchstart = (e) => {
      recordAndMaybeFlush(() => pushTouches(e.changedTouches, 'touchstart', now()));
    };
    const handleTouchmove = (e) => {
      const t = now();
      if (t - lastTouchMoveRef.current < MOVE_SAMPLE_INTERVAL_MS) return;
      lastTouchMoveRef.current = t;
      recordAndMaybeFlush(() => pushTouches(e.changedTouches, 'touchmove', t));
    };
    const handleTouchend = (e) => {
      recordAndMaybeFlush(() => pushTouches(e.changedTouches, 'touchend', now()));
    };

    window.addEventListener('keydown', handleKeydown);
    window.addEventListener('keyup', handleKeyup);
    window.addEventListener('mousedown', handleMousedown);
    window.addEventListener('mouseup', handleMouseup);
    window.addEventListener('mousemove', handleMousemove);
    window.addEventListener('touchstart', handleTouchstart, { passive: true });
    window.addEventListener('touchmove', handleTouchmove, { passive: true });
    window.addEventListener('touchend', handleTouchend, { passive: true });

    const intervalId = setInterval(flush, FLUSH_INTERVAL_MS);
    const handleBeforeUnload = () => flush();
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('keydown', handleKeydown);
      window.removeEventListener('keyup', handleKeyup);
      window.removeEventListener('mousedown', handleMousedown);
      window.removeEventListener('mouseup', handleMouseup);
      window.removeEventListener('mousemove', handleMousemove);
      window.removeEventListener('touchstart', handleTouchstart);
      window.removeEventListener('touchmove', handleTouchmove);
      window.removeEventListener('touchend', handleTouchend);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      clearInterval(intervalId);
      flush(); // best-effort flush on logout/unmount
    };
  }, [enabled, flush]);

  return { flushNow: flush };
}

export { useBehavioralCapture };
