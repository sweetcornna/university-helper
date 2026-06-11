/* University Helper · 帮助文档：目录高亮 + 复制按钮 */
(function () {
  'use strict';

  /* ---------- 目录滚动高亮 ---------- */
  var tocLinks = Array.prototype.slice.call(
    document.querySelectorAll('#wiki-toc a[href^="#"]')
  );
  var targets = tocLinks
    .map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); })
    .filter(Boolean);

  function activate(id) {
    tocLinks.forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('href') === '#' + id);
    });
  }

  if ('IntersectionObserver' in window && targets.length) {
    var visible = new Set();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) visible.add(e.target.id);
        else visible.delete(e.target.id);
      });
      // 取文档顺序中第一个可见的目标
      for (var i = 0; i < targets.length; i++) {
        if (visible.has(targets[i].id)) { activate(targets[i].id); return; }
      }
    }, { rootMargin: '-80px 0px -55% 0px' });
    targets.forEach(function (t) { io.observe(t); });
  }

  /* ---------- 复制按钮 ---------- */
  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy') || '';
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = '已复制 ✓';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.textContent = '复制';
          btn.classList.remove('copied');
        }, 1800);
      });
    });
  });
})();
