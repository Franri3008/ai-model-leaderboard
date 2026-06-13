(function (global) {
  const LB = global.LB = global.LB || {};

  const UNTRACKED_BADGE_HTML =
    '<span class="untracked-mark" style="display:inline-block;width:13px;height:13px;border-radius:50%;background:#888;color:#fff;font-size:9px;font-weight:700;text-align:center;line-height:13px;vertical-align:middle;">!</span>';

  const UNTRACKED_DISCLAIMER_HTML =
    '<div style="margin-top:6px;font-size:11px;color:#bbb;font-style:italic;text-align:center;">! Model stopped being tracked</div>';

  const DEACTIVATED_DISCLAIMER_HTML =
    '<div style="margin-top:6px;font-size:11px;color:#bbb;font-style:italic;text-align:center;">! This model got deactivated.</div>';

  const DEACTIVATED_COLOR = '#9ca3af';

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

  function position(tooltip, event, options = {}) {
    const offsetX = options.offsetX == null ? 12 : options.offsetX;
    const offsetY = options.offsetY == null ? -8 : options.offsetY;
    const node = typeof tooltip.node === 'function' ? tooltip.node() : tooltip;
    const pageX = event.pageX == null ? event.clientX + window.scrollX : event.pageX;
    const pageY = event.pageY == null ? event.clientY + window.scrollY : event.pageY;
    const clientX = event.clientX == null ? pageX - window.scrollX : event.clientX;
    const placeRight = clientX < window.innerWidth / 2;
    const tooltipWidth = node ? node.offsetWidth : 0;
    const left = placeRight ? pageX + offsetX : pageX - tooltipWidth - offsetX;
    const top = pageY + offsetY;

    if (typeof tooltip.style === 'function') {
      tooltip.style('left', left + 'px').style('top', top + 'px');
    } else if (node) {
      node.style.left = left + 'px';
      node.style.top = top + 'px';
    }

    return placeRight ? 'right' : 'left';
  }

  LB.tooltip = {
    renderScoreCell,
    position,
    badgeHtml: UNTRACKED_BADGE_HTML,
    disclaimerHtml: UNTRACKED_DISCLAIMER_HTML,
    deactivatedDisclaimerHtml: DEACTIVATED_DISCLAIMER_HTML,
    deactivatedColor: DEACTIVATED_COLOR
  };
})(typeof window !== 'undefined' ? window : globalThis);
