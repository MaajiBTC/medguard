// Small in-memory accumulator for raw behavioral events between flushes.
// Kept deliberately dumb: no dedupe, no derived features -- this module only
// buffers what useBehavioralCapture hands it and hands it back on drain().

function createEventBuffer() {
  let keystrokeEvents = [];
  let mouseEvents = [];
  let touchEvents = [];

  return {
    pushKeystroke(event) {
      keystrokeEvents.push(event);
    },
    pushMouse(event) {
      mouseEvents.push(event);
    },
    pushTouch(event) {
      touchEvents.push(event);
    },
    size() {
      return keystrokeEvents.length + mouseEvents.length + touchEvents.length;
    },
    isEmpty() {
      return keystrokeEvents.length === 0 && mouseEvents.length === 0 && touchEvents.length === 0;
    },
    /** Returns the buffered batch and clears the buffer. */
    drain() {
      const batch = {
        keystroke_events: keystrokeEvents,
        mouse_events: mouseEvents,
        touch_events: touchEvents,
      };
      keystrokeEvents = [];
      mouseEvents = [];
      touchEvents = [];
      return batch;
    },
  };
}

export { createEventBuffer };
