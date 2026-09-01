(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.MRDScannerHID = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const DEFAULTS = {minLength: 3, fastKeyMs: 220, fastRatio: 0.6, resetMs: 5000, dedupeMs: 900};

  class Detector {
    constructor(options) {
      this.config = Object.assign({}, DEFAULTS, options || {});
      this.clear();
      this.lastDispatch = {code: '', at: -Infinity};
    }
    clear() { this.buffer = ''; this.stamps = []; this.lastAt = null; }
    feed(key, at, completeValue) {
      const now = Number(at);
      const terminator = key === '\r' ? 'CR' : key === '\n' ? 'LF' : key;
      if (['Enter', 'Tab', 'CR', 'LF'].includes(terminator)) {
        const intervals = this.stamps.slice(1).map((stamp, index) => stamp - this.stamps[index]);
        const fast = intervals.filter(ms => ms <= this.config.fastKeyMs).length;
        const fastRatio = intervals.length ? fast / intervals.length : 0;
        const averageMs = intervals.length
          ? intervals.reduce((total, ms) => total + ms, 0) / intervals.length
          : 0;
        const code = String(completeValue == null ? this.buffer : completeValue).trim();
        const scannerLike = code.length >= this.config.minLength && fastRatio >= this.config.fastRatio;
        this.clear();
        const duplicate = scannerLike && this.lastDispatch.code === code && now - this.lastDispatch.at < this.config.dedupeMs;
        if (scannerLike && !duplicate) this.lastDispatch = {code, at: now};
        return {terminated: true, code, scannerLike, duplicate, fastRatio, averageMs, terminator};
      }
      if (String(key).length !== 1) return {terminated: false};
      if (this.lastAt != null && now - this.lastAt > this.config.resetMs) this.clear();
      this.buffer += key;
      this.stamps.push(now);
      if (this.stamps.length > 512) this.stamps.shift();
      this.lastAt = now;
      return {terminated: false};
    }
  }
  return {Detector, DEFAULTS};
});
