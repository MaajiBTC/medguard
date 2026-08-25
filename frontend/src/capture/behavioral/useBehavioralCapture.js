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
 * Attaches keystroke/mouse/touch listeners, flushing to POST
 * /api/captures/behavioral/events/ periodically.
 *
 * Keystroke capture only ever computes derived, anonymized timing features
 * (flight/digraph/trigraph latency, error/correction rate, rhythm consistency,
 * automation flags) -- never raw key identity. See keystrokeFeatures.js and
 * CLAUDE.md's Behavioral Signal Capture Module section. That's what makes it safe
 * to run this on LoginPage too, alongside the login-specific one-shot capture in
 * LoginPage.jsx itself (this hook covers the rest of the authenticated session).
 *
 * Per CLAUDE.md's capture spec: mousedown/mouseup are captured in full (every
 * event); mousemove/touchmove are throttled to ~15ms sampling since raw mousemove
 * fires far faster than that. No matching/scoring happens here (that's the
 * Scoring Engine, step 2) -- computing anonymized keystroke features is data
 * reduction for privacy, not a baseline comparison or access decision.
 *
 * @param {object} [options]
 * @param {boolean} [options.enabled] - set false to detach without unmounting.
 * @param {boolean} [options.captureKeystrokes] - set false to skip keydown/keyup
 *   listeners entirely (LoginPage handles keystrokes itself, scoped to just the
 *   username/password inputs, so it doesn't double up with this hook's global ones).
 * @returns {{ flushNow: () => void }}
 */
function useBehavioralCapture({ enabled = true, captureKeystrokes = true } = {}) {
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
      recordAndMaybeFlush(() => buffer.recordKeyDown(e.key, now()));
    };
    const handleKeyup = (e) => {
      recordAndMaybeFlush(() => buffer.recordKeyUp(e.key, now()));
    };
    const handlePaste = () => {
      recordAndMaybeFlush(() => buffer.recordPaste());
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

    if (captureKeystrokes) {
      window.addEventListener('keydown', handleKeydown);
      window.addEventListener('keyup', handleKeyup);
      window.addEventListener('paste', handlePaste);
    }
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
      if (captureKeystrokes) {
        window.removeEventListener('keydown', handleKeydown);
        window.removeEventListener('keyup', handleKeyup);
        window.removeEventListener('paste', handlePaste);
      }
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
  }, [enabled, captureKeystrokes, flush]);

  return { flushNow: flush };
}

export { useBehavioralCapture };
