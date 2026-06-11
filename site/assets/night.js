/* University Helper · 展示页「一夜」动效
   滚动 = 22:00 → 06:00；GSAP 未加载时整页保持静态可读。 */
(function () {
  'use strict';

  /* ---------- 星空（无 GSAP 也生成，CSS 自行闪烁） ---------- */
  var starsBox = document.getElementById('stars');
  if (starsBox) {
    var frag = document.createDocumentFragment();
    for (var i = 0; i < 110; i++) {
      var s = document.createElement('i');
      s.className = 'star';
      // 伪随机：基于索引的散列，避免每次构建结果不同
      var h = Math.sin(i * 127.1) * 43758.5453;
      var rx = h - Math.floor(h);
      var h2 = Math.sin(i * 311.7) * 26951.3571;
      var ry = h2 - Math.floor(h2);
      s.style.left = (rx * 100).toFixed(2) + '%';
      s.style.top = (ry * 72).toFixed(2) + '%';
      s.style.setProperty('--tw-dur', (2.4 + rx * 3.6).toFixed(2) + 's');
      s.style.setProperty('--tw-delay', (ry * 4).toFixed(2) + 's');
      s.style.setProperty('--tw-peak', (0.45 + rx * 0.5).toFixed(2));
      if (i % 9 === 0) { s.style.width = '3px'; s.style.height = '3px'; }
      frag.appendChild(s);
    }
    starsBox.appendChild(frag);
  }

  if (!window.gsap) return; // CDN 失效：保持静态页面
  gsap.registerPlugin(ScrollTrigger);
  document.documentElement.classList.add('js-anim');

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 时钟与天色：整页滚动进度 = 一夜 ---------- */
  var clockEl = document.getElementById('hud-clock');
  var phaseEl = document.getElementById('hud-phase');
  var progEl = document.getElementById('night-progress-fill');
  var hudEl = document.querySelector('.hud');
  var predawn = document.querySelector('.sky-predawn');
  var dawnSky = document.querySelector('.sky-dawn');
  var nightSky = document.querySelector('.sky-night');

  function ramp(p, a, b) { return Math.min(1, Math.max(0, (p - a) / (b - a))); }

  function setNight(p) {
    var mins = 22 * 60 + p * 480; // 22:00 起，共 8 小时
    var hh = Math.floor(mins / 60) % 24;
    var mm = Math.floor(mins % 60);
    if (clockEl) clockEl.textContent = (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
    if (phaseEl) {
      phaseEl.textContent =
        p < 0.18 ? '晚自习' :
        p < 0.45 ? '深夜' :
        p < 0.72 ? '凌晨' :
        p < 0.92 ? '将明' : '天亮';
    }
    if (progEl) progEl.style.transform = 'scaleX(' + p + ')';
    if (predawn) predawn.style.opacity = ramp(p, 0.3, 0.62);
    if (dawnSky) dawnSky.style.opacity = ramp(p, 0.7, 0.95);
    if (nightSky) nightSky.style.opacity = 1 - 0.5 * ramp(p, 0.3, 0.7);
    if (starsBox) starsBox.style.opacity = 1 - ramp(p, 0.62, 0.88);
    if (hudEl) hudEl.style.setProperty('--hud-a', (0.82 * (1 - ramp(p, 0.66, 0.92))).toFixed(3));
    document.body.classList.toggle('lit', p > 0.82);
  }

  /* ---------- 时刻导航高亮 ---------- */
  var railLinks = {};
  document.querySelectorAll('.hour-rail a').forEach(function (a) {
    railLinks[a.getAttribute('data-rail')] = a;
  });
  function railActivate(key) {
    Object.keys(railLinks).forEach(function (k) {
      railLinks[k].classList.toggle('active', k === key);
    });
  }
  var railSections = [
    ['top', document.querySelector('.hero')],
    ['access', document.getElementById('access')],
    ['engine', document.getElementById('engine')],
    ['isolation', document.getElementById('isolation')],
    ['start', document.getElementById('start')],
    ['dawn', document.getElementById('dawn')]
  ];
  function updateRail() {
    var key = 'top';
    var threshold = window.innerHeight * 0.55;
    railSections.forEach(function (pair) {
      if (pair[1] && pair[1].getBoundingClientRect().top <= threshold) key = pair[0];
    });
    railActivate(key);
  }

  /* 时刻锚点：区段经过视口中线时，时钟恰好走到它标注的时刻。
     固定区段会改变文档总高，因此一切都按实时位置计算、不做缓存。 */
  var timeAnchors = [
    { sel: null, mins: 22 * 60 },          // 页面顶部 → 22:00
    { sel: '#access', mins: 23.5 * 60 },   // 23:30
    { sel: '#engine', mins: 25 * 60 },     // 01:00
    { sel: '#isolation', mins: 27 * 60 },  // 03:00
    { sel: '#start', mins: 28.5 * 60 },    // 04:30
    { sel: 'end', mins: 30 * 60 }          // 页面底部 → 06:00
  ];
  function anchorY(def, max) {
    if (def.sel === null) return 0;
    if (def.sel === 'end') return max;
    var el = document.querySelector(def.sel);
    if (!el) return 0;
    // 被钉住的元素会平移，用 pin-spacer 的位置才稳定
    var box = el.parentElement && el.parentElement.classList.contains('pin-spacer')
      ? el.parentElement : el;
    var y = box.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.45;
    return Math.max(0, Math.min(max, y));
  }
  function minutesAt(y, max) {
    var pts = timeAnchors.map(function (d) { return { y: anchorY(d, max), t: d.mins }; });
    for (var i = 1; i < pts.length; i++) if (pts[i].y < pts[i - 1].y) pts[i].y = pts[i - 1].y;
    if (y <= pts[0].y) return pts[0].t;
    for (var j = 1; j < pts.length; j++) {
      if (y <= pts[j].y) {
        var f = (y - pts[j - 1].y) / Math.max(1, pts[j].y - pts[j - 1].y);
        return pts[j - 1].t + f * (pts[j].t - pts[j - 1].t);
      }
    }
    return pts[pts.length - 1].t;
  }

  var rafPending = false;
  function onNightScroll() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () {
      rafPending = false;
      var max = document.documentElement.scrollHeight - window.innerHeight;
      var y = Math.min(Math.max(0, window.scrollY), max);
      var mins = minutesAt(y, max);
      var p = Math.min(1, Math.max(0, (mins - 22 * 60) / 480));
      setNight(p);
      updateRail();
    });
  }
  window.addEventListener('scroll', onNightScroll, { passive: true });
  window.addEventListener('resize', onNightScroll, { passive: true });
  onNightScroll();

  if (reduced) {
    /* 减弱动效：全部呈现最终状态，仅保留滚动联动的时钟天色 */
    gsap.set('.shift-bar i, .ticket-bar i', { scaleX: 1 });
    document.querySelectorAll('.ticket-bar i').forEach(function (el) { el.classList.add('is-done'); });
    var pct = document.getElementById('ticket-pct');
    var st = document.getElementById('ticket-state');
    if (pct) pct.textContent = '100%';
    if (st) { st.textContent = '✓ 已完成'; st.classList.add('is-done'); }
    return;
  }

  /* ---------- 英雄区入场 ---------- */
  var intro = gsap.timeline({ defaults: { ease: 'expo.out' } });
  intro
    .fromTo('.couplet-banner', { autoAlpha: 0, y: -16 }, { autoAlpha: 1, y: 0, duration: 0.7 }, 0.1)
    .fromTo('.strip b', { autoAlpha: 0, y: -30 }, { autoAlpha: 1, y: 0, duration: 0.9, stagger: 0.09 }, 0.25)
    .fromTo('[data-hero]', { autoAlpha: 0, y: 26 }, { autoAlpha: 1, y: 0, duration: 0.9, stagger: 0.09 }, 0.5);

  /* ---------- 通用滚动显现 ---------- */
  gsap.utils.toArray('[data-reveal]').forEach(function (el) {
    gsap.fromTo(el,
      { autoAlpha: 0, y: 34 },
      {
        autoAlpha: 1, y: 0,
        duration: 0.95,
        delay: parseFloat(el.getAttribute('data-delay') || 0),
        ease: 'expo.out',
        scrollTrigger: { trigger: el, start: 'top 84%', once: true }
      });
  });

  /* ---------- 英雄任务票：循环演示 ---------- */
  (function ticketLoop() {
    var fill = document.getElementById('ticket-fill');
    var pct = document.getElementById('ticket-pct');
    var state = document.getElementById('ticket-state');
    var course = document.getElementById('ticket-course');
    if (!fill || !pct || !state || !course) return;
    var courses = [
      '形势与政策 · 第 3 章',
      '大学生心理健康 · 第 4 讲',
      '军事理论 · 第 9 讲',
      '创新创业基础 · 章节测验'
    ];
    var idx = 0;
    var prog = { v: 0 };
    function run() {
      course.textContent = courses[idx % courses.length];
      state.textContent = '视频播放中';
      state.classList.remove('is-done');
      fill.classList.remove('is-done');
      prog.v = 0;
      gsap.set(fill, { scaleX: 0 });
      gsap.to(prog, {
        v: 1, duration: 5.5, ease: 'power1.inOut',
        onUpdate: function () {
          gsap.set(fill, { scaleX: prog.v });
          pct.textContent = Math.round(prog.v * 100) + '%';
        },
        onComplete: function () {
          fill.classList.add('is-done');
          state.textContent = '✓ 已完成';
          state.classList.add('is-done');
          gsap.fromTo(state, { scale: 0.6 }, { scale: 1, duration: 0.35, ease: 'back.out(2.2)' });
          idx++;
          gsap.delayedCall(1.6, run);
        }
      });
    }
    run();
  })();

  /* ---------- 流星：偶尔划过 ---------- */
  (function meteors() {
    var m = document.getElementById('meteor');
    if (!m) return;
    var seed = 0;
    function shoot() {
      seed++;
      var h = Math.sin(seed * 91.7) * 10000;
      var r = h - Math.floor(h);
      m.style.top = (6 + r * 26) + '%';
      m.style.left = (35 + r * 50) + '%';
      gsap.fromTo(m,
        { opacity: 0, x: 0, y: 0 },
        {
          opacity: 0.9, x: -160, y: 100, duration: 1.1, ease: 'power2.in',
          onUpdate: function () { if (this.progress() > 0.7) m.style.opacity = (1 - this.progress()) * 3; },
          onComplete: function () { gsap.delayedCall(5 + r * 7, shoot); }
        });
    }
    gsap.delayedCall(3, shoot);
  })();

  /* ---------- 01:00 夜班：滚动驱动任务逐项完成 ---------- */
  var mm = gsap.matchMedia();

  mm.add('(min-width: 861px)', function () {
    var items = gsap.utils.toArray('.shift-item');
    var logs = gsap.utils.toArray('.log-line');
    var tl = gsap.timeline({
      scrollTrigger: {
        trigger: '#engine',
        start: 'top top',
        end: '+=2400',
        scrub: 0.5,
        pin: true,
        anticipatePin: 1
      }
    });
    items.forEach(function (item, i) {
      var bar = item.querySelector('.shift-bar i');
      var done = item.querySelector('.shift-done');
      var t = i * 1.0;
      tl.from(item, { autoAlpha: 0.18, x: 26, duration: 0.3, ease: 'power2.out' }, t)
        .to(bar, { scaleX: 1, duration: 0.55, ease: 'none' }, t + 0.18)
        .fromTo(done,
          { autoAlpha: 0, scale: 0.4 },
          { autoAlpha: 1, scale: 1, duration: 0.18, ease: 'back.out(2.5)' }, t + 0.74);
      if (logs[i]) tl.fromTo(logs[i], { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.2 }, t + 0.2);
      if (logs[i + 1] && i === items.length - 1) {
        tl.fromTo(logs[i + 1], { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.2 }, t + 0.8);
      }
    });
    // 队列里多出的日志行依次补上
    logs.slice(items.length + 1).forEach(function (line, j) {
      tl.fromTo(line, { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.2 }, items.length + j * 0.3);
    });
    tl.fromTo('#shift-clear',
      { autoAlpha: 0, y: 12 },
      { autoAlpha: 1, y: 0, duration: 0.4, ease: 'expo.out' }, items.length - 0.1);
    return function () {};
  });

  mm.add('(max-width: 860px)', function () {
    /* 小屏：不固定，逐项进入视口即完成 */
    gsap.utils.toArray('.shift-item').forEach(function (item, i) {
      var bar = item.querySelector('.shift-bar i');
      var done = item.querySelector('.shift-done');
      var tl = gsap.timeline({
        scrollTrigger: { trigger: item, start: 'top 86%', once: true }
      });
      tl.from(item, { autoAlpha: 0, y: 22, duration: 0.5, ease: 'expo.out' })
        .to(bar, { scaleX: 1, duration: 0.7, ease: 'power1.inOut' }, 0.15)
        .fromTo(done,
          { autoAlpha: 0, scale: 0.4 },
          { autoAlpha: 1, scale: 1, duration: 0.3, ease: 'back.out(2.2)' }, 0.8);
    });
    gsap.utils.toArray('.log-line').forEach(function (line, i) {
      gsap.fromTo(line, { autoAlpha: 0 }, {
        autoAlpha: 1, duration: 0.4, delay: i * 0.06,
        scrollTrigger: { trigger: '.shift-log', start: 'top 88%', once: true }
      });
    });
    gsap.fromTo('#shift-clear', { autoAlpha: 0 }, {
      autoAlpha: 1, duration: 0.6,
      scrollTrigger: { trigger: '#shift-clear', start: 'top 92%', once: true }
    });
    return function () {};
  });

  /* ---------- 03:50 跑马灯 ---------- */
  gsap.to('#marquee-track', { xPercent: -50, repeat: -1, ease: 'none', duration: 36 });

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
