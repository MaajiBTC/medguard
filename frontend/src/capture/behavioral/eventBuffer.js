// Small in-memory accumulator for behavioral events/keystrokes between flushes.
// Mouse/touch stay dumb raw arrays; keystrokes go through the keystroke
// accumulator so only derived, anonymized features ever leave the browser (see
// keystrokeFeatures.js).

import { computeKeystrokeFeatures, createKeystrokeAccumulator } from './keystrokeFeatures';

function createEventBuffer() {
  const keystrokeAccumulator = createKeystrokeAccumulator();
  let mouseEvents = [];
  let touchEvents = [];

  return {
    recordKeyDown(key, t) {
      keystrokeAccumulator.recordDown(key, t);
    },
    recordKeyUp(key, t) {
      keystrokeAccumulator.recordUp(key, t);
    },
    recordPaste() {
      keystrokeAccumulator.recordPaste();
    },
    pushMouse(event) {
      mouseEvents.push(event);
    },
    pushTouch(event) {
      touchEvents.push(event);
    },
    size() {
      return keystrokeAccumulator.count() + mouseEvents.length + touchEvents.length;
    },
    isEmpty() {
      return keystrokeAccumulator.isEmpty() && mouseEvents.length === 0 && touchEvents.length === 0;
    },
    /** Returns the buffered batch and clears the buffer. */
    drain() {
      const batch = {
        keystroke_features: computeKeystrokeFeatures(keystrokeAccumulator.drain()),
        mouse_events: mouseEvents,
        touch_events: touchEvents,
      };
      mouseEvents = [];
      touchEvents = [];
      return batch;
    },
  };
}

export { createEventBuffer };
