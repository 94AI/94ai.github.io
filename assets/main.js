// 94AI 共用腳本
(function () {
  // 回到頂端按鈕 + 英雄火花特效
  var btn = document.getElementById('backToTop');
  if (btn) {
    var onScroll = function () { btn.classList.toggle('show', window.scrollY > 200); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    var spawnSparks = function (x, y, count) {
      for (var i = 0; i < count; i++) {
        var s = document.createElement('span');
        s.className = 'spark';
        s.style.setProperty('--dx', (-40 - Math.random() * 60) + 'px');
        s.style.setProperty('--dy', (-20 - Math.random() * 120) + 'px');
        s.style.left = (x + (Math.random() * 20 - 10)) + 'px';
        s.style.top = (y + (Math.random() * 20 - 10)) + 'px';
        document.body.appendChild(s);
        s.addEventListener('animationend', function () { this.remove(); });
      }
    };

    btn.addEventListener('click', function () {
      btn.classList.add('comet');
      var r = btn.getBoundingClientRect();
      spawnSparks(r.left + r.width / 2, r.top + r.height / 2, 16);
      setTimeout(function () { btn.classList.remove('comet'); }, 650);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // 部落格分頁切換
  var tabs = document.querySelectorAll('[role="tab"]');
  var select = function (tab) {
    tabs.forEach(function (t) {
      var selected = t === tab;
      t.setAttribute('aria-selected', selected ? 'true' : 'false');
      document.getElementById(t.getAttribute('aria-controls')).hidden = !selected;
    });
  };
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () { select(tab); });
  });
  // 網址帶 #youtube 時，直接打開 YouTube 區
  if (location.hash === '#youtube') {
    var yt = document.getElementById('tab-youtube');
    if (yt) select(yt);
  }
})();
