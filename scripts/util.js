(function (global) {
  const LB = global.LB = global.LB || {};

  function parseNum(v) {
    if (v == null) return 0;
    const s = String(v).replace(/,/g, '.');
    const n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  }

  function parseDate(s) {
    if (!s) return null;
    const t = String(s).trim();
    if (!t) return null;
    const d = new Date(t);
    return isNaN(d.getTime()) ? null : d;
  }

  function displayName(name) {
    if (!name) return '';
    return String(name)
      .replace(/\s*\((Thinking|Preview|Beta)\)\s*/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function hexToRgb(hex) {
    const s = hex.replace('#', '');
    const v = s.length === 3 ? s.split('').map(ch => ch + ch).join('') : s;
    const n = parseInt(v, 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  function rgbToHex(r, g, b) {
    const toHex = x => x.toString(16).padStart(2, '0');
    return '#' + toHex(r) + toHex(g) + toHex(b);
  }

  function lighten(hex, amt) {
    if (!hex) return null;
    const { r, g, b } = hexToRgb(hex);
    const lr = Math.min(255, Math.round(r + (255 - r) * amt));
    const lg = Math.min(255, Math.round(g + (255 - g) * amt));
    const lb = Math.min(255, Math.round(b + (255 - b) * amt));
    return rgbToHex(lr, lg, lb);
  }

  function clampToDomain(value, domain) {
    if (!domain || domain.length < 2) return value || 0;
    const num = Number(value);
    const safe = isNaN(num) ? domain[0] : num;
    return Math.max(domain[0], Math.min(domain[1], safe));
  }

  LB.util = { parseNum, parseDate, displayName, hexToRgb, rgbToHex, lighten, clampToDomain };
})(typeof window !== 'undefined' ? window : globalThis);
