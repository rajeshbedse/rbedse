/* RYB Finserv — watermark visibility / transparent cards v4 */
(function () {
  'use strict';
  function apply() {
    if (!document.head || document.getElementById('scan-watermark-visibility-hotfix')) return;
    var style = document.createElement('style');
    style.id = 'scan-watermark-visibility-hotfix';
    style.textContent = [
      '.stock-detail>.detail-watermark{position:absolute!important;inset:0!important;z-index:0!important;opacity:1!important;display:block!important}',
      '.stock-detail>.detail-watermark>svg{position:absolute!important;top:50%!important;left:50%!important;width:78%!important;height:78%!important;transform:translate(-50%,-42%)!important;opacity:.16!important;z-index:0!important}',
      '.stock-detail .detail-hero{background:transparent!important}',
      '.stock-detail .detail-score-block{background:rgba(248,251,255,.52)!important}',
      '.stock-detail .detail-tabs{background:transparent!important}',
      '.stock-detail .detail-panel{background:transparent!important}',
      '.stock-detail .overview-card{background:rgba(255,255,255,.42)!important}',
      '.stock-detail .dd-card{background:rgba(255,255,255,.42)!important}',
      '.stock-detail .dd-card.promoter{background:rgba(246,255,250,.46)!important}',
      '.stock-detail .activity-grid{background:rgba(255,255,255,.36)!important}',
      '.stock-detail-header,.stock-detail .detail-hero,.stock-detail .detail-decision-flow,.stock-detail .detail-tabs,.stock-detail .detail-panel{position:relative!important;z-index:1!important}',
      '@media(max-width:640px){.stock-detail>.detail-watermark>svg{width:125%!important;height:68%!important;opacity:.13!important}.stock-detail .overview-card{background:rgba(255,255,255,.40)!important}.stock-detail .dd-card{background:rgba(255,255,255,.40)!important}.stock-detail .dd-card.promoter{background:rgba(246,255,250,.44)!important}.stock-detail .activity-grid{background:rgba(255,255,255,.34)!important}}'
    ].join('');
    document.head.appendChild(style);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, {once:true});
  else apply();
})();
