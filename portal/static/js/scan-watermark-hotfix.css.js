/* RYB Finserv — PROD watermark visibility hotfix v2 */
(function () {
  'use strict';
  function apply() {
    if (!document.head || document.getElementById('scan-watermark-visibility-hotfix')) return;
    var style = document.createElement('style');
    style.id = 'scan-watermark-visibility-hotfix';
    style.textContent = [
      '.stock-detail>.detail-watermark>svg{opacity:.10!important}',
      '.stock-detail>.detail-watermark{opacity:1!important}',
      '.stock-detail .overview-card{background:rgba(255,255,255,.74)!important}',
      '.stock-detail .dd-card{background:rgba(255,255,255,.74)!important}',
      '.stock-detail .dd-card.promoter{background:rgba(246,255,250,.78)!important}',
      '.stock-detail .activity-grid{background:rgba(255,255,255,.66)!important}',
      '.stock-detail .detail-score-block{background:rgba(248,251,255,.78)!important}'
    ].join('');
    document.head.appendChild(style);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, {once:true});
  else apply();
})();
