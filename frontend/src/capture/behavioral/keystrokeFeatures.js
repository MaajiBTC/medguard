// Derived, anonymized keystroke-dynamics features — never raw key identity.
//
// The only key identity ever inspected is Backspace/Delete (a control key, not a
// password character), used solely to count corrections. Digraph/trigraph latency
// is indexed by keystroke POSITION, never by which character was pressed: a person
// retypes the same credential in the same order every login, so position carries
// the same matching value character-labeling would, with zero password content ever
// leaving the browser. See CLAUDE.md's Behavioral Signal Capture Module section.

const IMPOSSIBLY_FAST_FLIGHT_MS = 20;
const ZERO_VARIANCE_THRESHOLD = 3; // ms stdev below this reads as scripted input

function createKeystrokeAccumulator() {
  const pending = new Map(); // key -> downT, keyed transiently to pair down/up
  const keystrokes = []; // [{ downT, upT, isCorrection }], in press order
  let pasted = false; // a paste never fires per-character keydown/keyup at all,
  // so it has to be tracked separately rather than inferred from timing.

  return {
    recordDown(key, t) {
      pending.set(key, t);
    },
    recordUp(key, t) {
      const downT = pending.get(key);
      if (downT === undefined) return; // stray keyup with no matching keydown (e.g. modifier held before capture started)
      pending.delete(key);
      keystrokes.push({
        downT,
        upT: t,
        isCorrection: key === 'Backspace' || key === 'Delete',
      });
    },
    recordPaste() {
      pasted = true;
    },
    drain() {
      const batch = keystrokes.slice();
      keystrokes.length = 0;
      pending.clear();
      const wasPasted = pasted;
      pasted = false;
      return { keystrokes: batch, pasted: wasPasted };
    },
    isEmpty() {
      return keystrokes.length === 0 && !pasted;
    },
    count() {
      return keystrokes.length;
    },
  };
}

function mean(values) {
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function stdev(values) {
  if (values.length < 2) return 0;
  const m = mean(values);
  return Math.sqrt(mean(values.map((v) => (v - m) ** 2)));
}

/** @param {{keystrokes: Array<{downT: number, upT: number, isCorrection: boolean}>, pasted: boolean}} accumulated */
function computeKeystrokeFeatures(accumulated) {
  const keystrokes = accumulated?.keystrokes || [];
  const pasted = accumulated?.pasted || false;

  if (keystrokes.length < 2) {
    return {
      flight_times: [],
      digraph_latencies: [],
      trigraph_latencies: [],
      error_correction_rate: 0,
      rhythm_consistency: 0,
      automation_flags: pasted ? ['paste_detected'] : [],
    };
  }

  const flightTimes = [];
  const digraphLatencies = [];
  const trigraphLatencies = [];

  for (let i = 0; i < keystrokes.length - 1; i += 1) {
    flightTimes.push(keystrokes[i + 1].downT - keystrokes[i].upT);
    digraphLatencies.push(keystrokes[i + 1].downT - keystrokes[i].downT);
  }
  for (let i = 0; i < keystrokes.length - 2; i += 1) {
    trigraphLatencies.push(keystrokes[i + 2].downT - keystrokes[i].downT);
  }

  const correctionCount = keystrokes.filter((k) => k.isCorrection).length;
  const errorCorrectionRate = correctionCount / keystrokes.length;

  const flightMean = mean(flightTimes);
  const flightStdev = stdev(flightTimes);
  const rhythmConsistency = flightMean > 0 ? Math.max(0, Math.min(1, 1 - flightStdev / flightMean)) : 0;

  const automationFlags = [];
  if (pasted) automationFlags.push('paste_detected');
  if (flightMean > 0 && flightMean < IMPOSSIBLY_FAST_FLIGHT_MS) automationFlags.push('impossibly_fast');
  if (flightTimes.length >= 3 && flightStdev < ZERO_VARIANCE_THRESHOLD) automationFlags.push('zero_variance');

  return {
    flight_times: flightTimes,
    digraph_latencies: digraphLatencies,
    trigraph_latencies: trigraphLatencies,
    error_correction_rate: errorCorrectionRate,
    rhythm_consistency: rhythmConsistency,
    automation_flags: automationFlags,
  };
}

export { createKeystrokeAccumulator, computeKeystrokeFeatures };
