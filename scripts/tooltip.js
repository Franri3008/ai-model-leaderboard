(function (global) {
  const LB = global.LB = global.LB || {};

  const UNTRACKED_BADGE_HTML =
    '<span class="untracked-mark" style="display:inline-block;width:13px;height:13px;border-radius:50%;background:#888;color:#fff;font-size:9px;font-weight:700;text-align:center;line-height:13px;vertical-align:middle;">!</span>';

  const UNTRACKED_DISCLAIMER_HTML =
    '<div style="margin-top:6px;font-size:11px;color:#bbb;font-style:italic;text-align:center;">! Model stopped being tracked</div>';

  function renderScoreCell(model, key, currentScore, formatter, lastTrackedScores) {
    if (currentScore > 0) return { html: formatter(currentScore), untracked: false };
    const last = lastTrackedScores && lastTrackedScores[model] && lastTrackedScores[model][key];
    if (last && last.value > 0) {
      return {
        html: '<span style="color:#888;">' + formatter(last.value) + '</span> ' + UNTRACKED_BADGE_HTML,
        untracked: true
      };
    }
    return { html: '-', untracked: false };
  }

  LB.tooltip = {
    renderScoreCell,
    badgeHtml: UNTRACKED_BADGE_HTML,
    disclaimerHtml: UNTRACKED_DISCLAIMER_HTML
  };
})(typeof window !== 'undefined' ? window : globalThis);
