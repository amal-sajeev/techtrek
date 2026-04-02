// ---- STARFIELD / LIGHT SPARKLES ----
(function(){
  var canvas = document.getElementById('starfield');
  if (!canvas) return;
  // Respect user's motion preference and skip canvas on low-memory devices
  var prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var lowMemory = navigator.deviceMemory !== undefined && navigator.deviceMemory < 2;
  if (prefersReduced || lowMemory) { canvas.style.display = 'none'; return; }
  var ctx = canvas.getContext('2d');
  var W, H, stars = [];
  var DARK_COUNT = 180;
  var LIGHT_COUNT = 260;
  var isDark = function() { return !document.documentElement.getAttribute('data-theme') || document.documentElement.getAttribute('data-theme') === 'dark'; };

  var MOTE_COLORS = [
    [230, 155, 20],
    [8,  129, 162],
    [232, 120, 23],
    [180, 215, 235],
    [190, 155, 240],
    [255, 200, 100],
  ];

  function resize(){
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function initStars(){
    stars = [];
    var count = isDark() ? DARK_COUNT : LIGHT_COUNT;
    for(var i = 0; i < count; i++){
      stars.push({
        x: Math.random() * W,
        y: Math.random() * H,
        r: Math.random() * 1.3 + 0.25,
        a: Math.random(),
        speed: Math.random() * 0.15 + 0.03,
        twinkle: Math.random() * Math.PI * 2,
        colorIdx: Math.floor(Math.random() * MOTE_COLORS.length)
      });
    }
  }

  var frame = 0;
  var rafId = null;
  function draw(){
    if(document.hidden || !canvas.offsetParent){ rafId = null; return; }
    ctx.clearRect(0,0,W,H);
    frame++;
    if(isDark()){
      for(var i = 0; i < stars.length; i++){
        var s = stars[i];
        s.twinkle += 0.015;
        var alpha = (s.a * 0.7 + 0.3) * (0.6 + Math.sin(s.twinkle) * 0.4);
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(200,230,255,' + alpha + ')';
        ctx.fill();
        s.y -= s.speed;
        if(s.y < -2){ s.y = H + 2; s.x = Math.random()*W; }
      }
      if(frame % 280 === 0) shootingStar();
    } else {
      for(var i = 0; i < stars.length; i++){
        var s = stars[i];
        s.twinkle += 0.012;
        var alpha = (s.a * 0.55 + 0.15) * (0.5 + Math.sin(s.twinkle) * 0.5);
        var c = MOTE_COLORS[s.colorIdx];
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha + ')';
        ctx.fill();
        s.y -= s.speed * 0.55;
        if(s.y < -2){ s.y = H + 2; s.x = Math.random()*W; }
      }
      if(frame % 360 === 0) lightFlare();
    }
    rafId = requestAnimationFrame(draw);
  }

  function startDraw(){ if(!rafId) rafId = requestAnimationFrame(draw); }
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) startDraw(); });

  function shootingStar(){
    var x = Math.random() * W * 0.7 + W * 0.15;
    var y = Math.random() * H * 0.4;
    var t = 0;
    var len = 120 + Math.random()*80;
    function animate(){
      t++;
      if(t > 30) return;
      var progress = t/30;
      var alpha = progress < 0.5 ? progress*2 : (1-progress)*2;
      var tail = len * progress;
      var grad = ctx.createLinearGradient(x,y,x+tail*0.7,y+tail*0.5);
      grad.addColorStop(0, 'rgba(0,212,255,0)');
      grad.addColorStop(1, 'rgba(0,212,255,' + alpha*0.8 + ')');
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + tail*0.7, y + tail*0.5);
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      requestAnimationFrame(animate);
    }
    animate();
  }

  function lightFlare(){
    var x = Math.random() * W * 0.8 + W * 0.1;
    var y = Math.random() * H * 0.7 + H * 0.1;
    var c = MOTE_COLORS[Math.floor(Math.random() * 3)];
    var t = 0;
    var len = 50 + Math.random() * 40;
    function animate(){
      t++;
      if(t > 40) return;
      var progress = t / 40;
      var alpha = (progress < 0.5 ? progress * 2 : (1 - progress) * 2) * 0.45;
      var grad = ctx.createLinearGradient(x, y, x + len, y - len * 0.3);
      grad.addColorStop(0, 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',0)');
      grad.addColorStop(1, 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha + ')');
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + len, y - len * 0.3);
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1;
      ctx.stroke();
      requestAnimationFrame(animate);
    }
    animate();
  }

  new MutationObserver(function() { initStars(); startDraw(); }).observe(
    document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }
  );

  window.addEventListener('resize', function(){ resize(); initStars(); });
  resize(); initStars(); startDraw();
})();

// ---- NAVBAR SCROLL ----
(function() {
  var navbar = document.getElementById('navbar');
  if (!navbar) return;
  window.addEventListener('scroll', function(){
    navbar.classList.toggle('scrolled', window.scrollY > 20);
  }, {passive:true});
})();

// ---- MOBILE NAV ----
(function(){
  var navToggle = document.getElementById('nav-toggle');
  var navDrawer = document.getElementById('nav-drawer');
  var navOverlay = document.getElementById('nav-overlay');
  if (!navToggle || !navDrawer) return;

  function closeDrawer(){ navDrawer.classList.remove('active'); navOverlay.classList.remove('active'); }
  navToggle.addEventListener('click', function(){ navDrawer.classList.toggle('active'); navOverlay.classList.toggle('active'); });
  if (navOverlay) navOverlay.addEventListener('click', closeDrawer);
})();

// ---- THEME TOGGLE ----
(function(){
  var themeBtn = document.getElementById('theme-toggle');
  function toggleTheme(){
    var isLight = document.documentElement.getAttribute('data-theme') === 'light';
    if(isLight){
      document.documentElement.removeAttribute('data-theme');
      localStorage.removeItem('techtrek-theme');
    } else {
      document.documentElement.setAttribute('data-theme','light');
      localStorage.setItem('techtrek-theme','light');
    }
  }
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
  var drawerThemeBtn = document.getElementById('drawer-theme-toggle');
  if(drawerThemeBtn) drawerThemeBtn.addEventListener('click', toggleTheme);
})();

// ---- FLASH DISMISS ----
document.querySelectorAll('.flash-close').forEach(function(btn){
  btn.addEventListener('click', function(){ btn.closest('.flash-message').remove(); });
});
setTimeout(function(){ document.querySelectorAll('.flash-message').forEach(function(el){ el.remove(); }); }, 5000);

// ---- SCROLL REVEAL ----
(function(){
  var revealObserver = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        e.target.classList.add('visible');
        revealObserver.unobserve(e.target);
      }
    });
  },{threshold:0.12});
  document.querySelectorAll('.reveal, .stagger').forEach(function(el){ revealObserver.observe(el); });
})();

// ---- GLOBAL FORM SUBMIT LOADING ----
document.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.hasAttribute('novalidate')) return;
  var btn = form.querySelector('[type=submit]:not([data-no-loading])');
  if (btn && !btn.disabled && !btn.classList.contains('btn-loading')) {
    btn.classList.add('btn-loading');
    var doDisable = function() {
      btn.disabled = true;
    };
    if (typeof requestAnimationFrame !== 'undefined') {
      requestAnimationFrame(function() { requestAnimationFrame(doDisable); });
    } else {
      setTimeout(doDisable, 0);
    }
    setTimeout(function() {
      btn.classList.remove('btn-loading');
      btn.disabled = false;
    }, 8000);
  }
}, true);

// ---- CONFIRM MODAL (with focus trap) ----
(function(){
  var confirmModal = document.getElementById('confirm-modal');
  if (!confirmModal) return;
  var confirmCallback = null;
  var lastFocused = null;

  function openConfirm(msg, cb, opts) {
    var clean = msg.replace(/\\n/g, '\n');
    var lines = clean.split('\n').filter(function(l) { return l.trim() !== ''; });
    var titleEl = confirmModal.querySelector('.modal-title');
    var bodyEl = confirmModal.querySelector('.confirm-message');
    titleEl.textContent = lines[0] || 'Are you sure?';
    if (lines.length > 1) {
      bodyEl.innerHTML = lines.slice(1).join('<br>');
      bodyEl.style.display = '';
    } else {
      bodyEl.innerHTML = '';
      bodyEl.style.display = 'none';
    }
    var ring = confirmModal.querySelector('.modal-icon-ring');
    ring.className = 'modal-icon-ring ' + ((opts && opts.iconClass) || 'modal-icon-warn');
    var yesBtn = confirmModal.querySelector('.confirm-yes');
    yesBtn.textContent = (opts && opts.confirmLabel) || 'Confirm';
    yesBtn.className = 'btn ' + ((opts && opts.confirmClass) || 'btn-danger');
    confirmCallback = cb;
    confirmModal.classList.add('active');
    lastFocused = document.activeElement;
    setTimeout(function() {
      var cancelBtn = confirmModal.querySelector('.confirm-no');
      if (cancelBtn) cancelBtn.focus();
    }, 50);
  }

  function closeConfirm() {
    confirmModal.classList.remove('active');
    confirmCallback = null;
    if (lastFocused) lastFocused.focus();
  }

  confirmModal.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeConfirm(); return; }
    if (e.key !== 'Tab') return;
    var focusable = confirmModal.querySelectorAll('button:not([disabled])');
    var first = focusable[0];
    var last  = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  confirmModal.querySelector('.confirm-yes').addEventListener('click', function() {
    var cb = confirmCallback;
    closeConfirm();
    if (cb) cb();
  });
  confirmModal.querySelector('.confirm-no').addEventListener('click', closeConfirm);
  confirmModal.querySelector('.modal-backdrop').addEventListener('click', closeConfirm);

  window.openConfirm = openConfirm;
  window.closeConfirm = closeConfirm;
})();

// ---- ADMIN SIDEBAR (mobile) ----
(function(){
  var aToggle = document.getElementById('admin-sidebar-toggle');
  var aSidebar = document.getElementById('admin-sidebar');
  var aOverlay = document.getElementById('admin-overlay');
  if(!aToggle || !aSidebar) return;
  function openAdmin(){ aSidebar.classList.add('open'); if(aOverlay) aOverlay.classList.add('open'); }
  function closeAdmin(){ aSidebar.classList.remove('open'); if(aOverlay) aOverlay.classList.remove('open'); }
  aToggle.addEventListener('click', function(){ aSidebar.classList.contains('open') ? closeAdmin() : openAdmin(); });
  if(aOverlay) aOverlay.addEventListener('click', closeAdmin);
})();

// ---- TOAST NOTIFICATIONS ----
function showToast(message, type, duration){
  type = type || 'info';
  duration = duration || 4000;
  var container = document.getElementById('toast-container');
  if(!container){
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.innerHTML = '<span class="toast-message">' + message + '</span><button class="toast-close">&times;</button>';
  container.appendChild(toast);
  requestAnimationFrame(function(){ toast.classList.add('toast-visible'); });
  var timer = setTimeout(function(){ removeToast(toast); }, duration);
  toast.querySelector('.toast-close').addEventListener('click', function(){ clearTimeout(timer); removeToast(toast); });
}
function removeToast(toast){
  toast.classList.remove('toast-visible');
  toast.classList.add('toast-hiding');
  setTimeout(function(){ toast.remove(); }, 500);
}

// ---- DATA-CONFIRM HANDLER ----
document.addEventListener('click', function(e) {
  var btn = e.target.closest('[data-confirm]');
  if (!btn) return;
  e.preventDefault();
  var msg = btn.getAttribute('data-confirm');
  var cls = btn.getAttribute('data-confirm-class') || 'btn-danger';
  var label = btn.getAttribute('data-confirm-label') || 'Confirm';
  openConfirm(msg, function() {
    var form = btn.closest('form');
    if (form) form.submit();
  }, { confirmClass: cls, confirmLabel: label });
}, true);

// ---- QR ZOOM ----
(function() {
  var qrModal = document.getElementById('qr-zoom-modal');
  if (!qrModal) return;
  var zoomImg = qrModal.querySelector('.qr-zoom-img');
  var zoomLabel = qrModal.querySelector('.qr-zoom-label');

  function openQR(src, label) {
    zoomImg.src = src;
    zoomLabel.textContent = label || '';
    zoomLabel.style.display = label ? '' : 'none';
    qrModal.classList.add('active');
  }
  function closeQR() {
    qrModal.classList.remove('active');
    zoomImg.src = '';
  }

  document.addEventListener('click', function(e) {
    var img = e.target.closest('.ticket-qr, .booking-qr-img');
    if (!img || !img.src) return;
    e.preventDefault();
    var label = img.getAttribute('alt') || '';
    openQR(img.src, label);
  });

  qrModal.querySelector('.qr-zoom-close').addEventListener('click', closeQR);
  qrModal.querySelector('.modal-backdrop').addEventListener('click', closeQR);
  qrModal.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeQR(); });
})();

// ---- GLOBAL API ----
function dismissFeedback(eventId, dontAsk) {
  var modal = document.getElementById('feedback-modal');
  if (modal) modal.style.display = 'none';
  var fd = new FormData();
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (csrfMeta) fd.append('csrf_token', csrfMeta.content);
  if (dontAsk) fd.append('dont_ask', '1');
  fetch('/feedback/' + eventId + '/dismiss', { method: 'POST', body: fd })
    .catch(function() { console.warn('Failed to dismiss feedback for event ' + eventId); });
}
window.TechTrek = { showToast: showToast, confirmAction: openConfirm, dismissFeedback: dismissFeedback };

// ---- POLL POPUP (only for logged-in users) ----
if (document.body.dataset.user) {
(function pollPopup() {
  var modal = document.getElementById('poll-popup-modal');
  if (!modal) return;
  var backdrop = document.getElementById('poll-popup-backdrop');
  var sessionEl = document.getElementById('poll-popup-session');
  var questionEl = document.getElementById('poll-popup-question');
  var bodyEl = document.getElementById('poll-popup-body');
  var totalEl = document.getElementById('poll-popup-total');
  var voteBtn = document.getElementById('poll-popup-vote-btn');
  var dismissBtn = document.getElementById('poll-popup-dismiss');
  var viewLink = document.getElementById('poll-popup-view-session');
  var currentSessionId = null;
  var currentEventId = null;
  var currentPollId = null;
  var currentPollType = 'multiple_choice';
  var votedOption = null;
  var votedRating = null;
  var votedText = null;

  function pollQS() {
    return currentEventId ? '?event_id=' + currentEventId : '';
  }

  function closePollModal() {
    modal.style.display = 'none';
  }
  function openPollModal() {
    modal.style.display = 'flex';
  }

  function hasVoted(data) {
    return (data.voted_option !== undefined && data.voted_option !== null) ||
      (data.voted_rating !== undefined && data.voted_rating !== null) ||
      (data.voted_text !== undefined && data.voted_text !== null && data.voted_text !== '');
  }

  function renderPollBody(data) {
    if (!data || !data.question) return;
    currentSessionId = data.session_id;
    currentEventId = data.event_id || null;
    currentPollId = data.poll_id;
    currentPollType = data.poll_type || 'multiple_choice';
    if (data.voted_option !== undefined && data.voted_option !== null) votedOption = data.voted_option;
    if (data.voted_rating !== undefined && data.voted_rating !== null) votedRating = data.voted_rating;
    if (data.voted_text !== undefined && data.voted_text !== null) votedText = data.voted_text;
    var readOnly = hasVoted(data);
    sessionEl.textContent = data.session_title ? 'From: ' + data.session_title : '';
    viewLink.href = currentSessionId ? '/sessions/' + currentSessionId : '#';
    questionEl.textContent = data.question;
    voteBtn.style.display = 'none';
    var html = '';
    var ptype = data.poll_type || 'multiple_choice';

    if (ptype === 'multiple_choice' || ptype === 'yes_no') {
      totalEl.textContent = (data.total_votes || 0) + ' vote' + (data.total_votes !== 1 ? 's' : '');
      if (readOnly) {
        var chosen = (data.options || []).find(function(opt) { return opt.id === votedOption; });
        html += '<div style="padding:.6rem .75rem;border-radius:6px;border:2px solid var(--cyan);background:rgba(0,212,255,.08);color:var(--text-primary)">' +
          '<span style="color:var(--cyan)">&#10003; Your answer: </span>' + (chosen ? chosen.text.replace(/</g,'&lt;').replace(/>/g,'&gt;') : '') + '</div>';
        if ((data.options || []).length) {
          html += '<div style="margin-top:.75rem;font-size:.85rem;color:var(--text-muted)">All options:</div>';
          (data.options || []).forEach(function(opt) {
            var isVoted = votedOption === opt.id;
            html += '<div style="margin-top:.25rem;padding:.35rem .5rem;border-radius:4px;' + (isVoted ? 'background:rgba(0,212,255,.06)' : '') + '">' +
              (isVoted ? '&#10003; ' : '') + opt.text.replace(/</g,'&lt;').replace(/>/g,'&gt;') + ' <span style="opacity:.8">(' + opt.votes + ', ' + opt.pct + '%)</span></div>';
          });
        }
      } else {
        (data.options || []).forEach(function(opt) {
          var isVoted = votedOption === opt.id;
          html += '<div style="margin-bottom:.5rem"><label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;padding:.5rem .6rem;border-radius:6px;border:1px solid var(--border,rgba(255,255,255,.12));' + (isVoted ? 'border-color:var(--cyan);background:rgba(0,212,255,.08)' : '') + '">' +
            '<input type="radio" name="poll-opt" value="' + opt.id + '" ' + (isVoted ? 'checked' : '') + ' style="flex-shrink:0">' +
            '<span style="flex:1">' + (isVoted ? '&#10003; ' : '') + opt.text + '</span>' +
            '<span style="font-size:.8rem;color:var(--text-muted)">' + opt.votes + ' (' + opt.pct + '%)</span></label></div>';
        });
        voteBtn.style.display = '';
      }
    } else if (ptype === 'rating') {
      var avg = data.average || 0;
      totalEl.textContent = (data.total_votes || 0) + ' rating' + (data.total_votes !== 1 ? 's' : '') + ' · avg ' + avg + '/5';
      if (readOnly) {
        html += '<div style="padding:.6rem .75rem;border-radius:6px;border:2px solid var(--cyan);background:rgba(0,212,255,.08);margin-bottom:.5rem">' +
          '<span style="color:var(--cyan)">&#10003; Your rating: </span>' + (votedRating || 0) + '/5</div>';
        html += '<div style="display:flex;justify-content:center;gap:.25rem;margin:.5rem 0">';
        for (var s = 1; s <= 5; s++) {
          var active = votedRating && s <= votedRating;
          html += '<span style="font-size:1.8rem;color:' + (active ? '#fbbf24' : 'var(--border,rgba(255,255,255,.2))') + '">&#9733;</span>';
        }
        html += '</div>';
      } else {
        html += '<div style="display:flex;justify-content:center;gap:.25rem;margin:.5rem 0" id="poll-popup-stars">';
        for (var s = 1; s <= 5; s++) {
          var active = votedRating && s <= votedRating;
          html += '<span class="poll-popup-star" data-val="' + s + '" style="font-size:1.8rem;cursor:pointer;color:' + (active ? '#fbbf24' : 'var(--border,rgba(255,255,255,.2))') + '">&#9733;</span>';
        }
        html += '</div>';
        voteBtn.style.display = '';
      }
    } else if (ptype === 'text') {
      totalEl.textContent = (data.total_votes || 0) + ' response' + (data.total_votes !== 1 ? 's' : '');
      if (readOnly) {
        html += '<div style="padding:.6rem .75rem;border-radius:6px;border:2px solid var(--cyan);background:rgba(0,212,255,.08)">' +
          '<span style="color:var(--cyan)">&#10003; Your answer: </span>' + (votedText || '').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
        if (data.responses && data.responses.length) {
          html += '<div style="margin-top:.75rem;font-size:.85rem;color:var(--text-muted)">Other responses:</div>';
          data.responses.slice(0, 5).forEach(function(r) {
            html += '<div style="padding:.35rem .5rem;background:var(--bg-void,#0d0d1a);border-radius:4px;margin-top:.25rem;font-size:.85rem">' + r.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
          });
        }
      } else {
        html += '<input type="text" id="poll-popup-text-inp" class="form-input" placeholder="Type your answer..." value="' + (votedText || '').replace(/"/g, '&quot;') + '" style="margin-bottom:.5rem">';
        voteBtn.style.display = '';
        if (data.responses && data.responses.length) {
          html += '<div style="max-height:120px;overflow-y:auto;font-size:.85rem">';
          data.responses.slice(0, 5).forEach(function(r) {
            html += '<div style="padding:.35rem .5rem;background:var(--bg-void,#0d0d1a);border-radius:4px;margin-bottom:.25rem">' + r.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
          });
          html += '</div>';
        }
      }
    }
    bodyEl.innerHTML = html;
    if (!readOnly && ptype === 'rating') {
      bodyEl.querySelectorAll('.poll-popup-star').forEach(function(star) {
        star.addEventListener('click', function() {
          var val = parseInt(star.dataset.val, 10);
          votedRating = val;
          bodyEl.querySelectorAll('.poll-popup-star').forEach(function(s) {
            s.style.color = parseInt(s.dataset.val) <= val ? '#fbbf24' : 'var(--border,rgba(255,255,255,.2))';
          });
          submitPollVote({ rating: val });
        });
      });
    }
    if (!readOnly) {
      bodyEl.querySelectorAll('input[name="poll-opt"]').forEach(function(radio) {
        radio.addEventListener('change', function() { votedOption = parseInt(this.value, 10); });
      });
    }
  }

  function submitPollVote(extra) {
    if (!currentSessionId || !currentPollId) return;
    var body = extra || {};
    if (currentPollType === 'multiple_choice' || currentPollType === 'yes_no') {
      if (votedOption == null) return;
      body.option_id = votedOption;
    } else if (currentPollType === 'text') {
      var inp = document.getElementById('poll-popup-text-inp');
      var text = (inp && inp.value) ? inp.value.trim() : '';
      if (!text) return;
      body.text = text;
    }
    voteBtn.disabled = true;
    fetch('/sessions/' + currentSessionId + '/polls/' + currentPollId + '/vote' + pollQS(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(r) { return r.json(); }).then(function(res) {
      voteBtn.disabled = false;
      if (res.ok && res.poll) {
        votedOption = res.poll.voted_option;
        votedRating = res.poll.voted_rating;
        votedText = res.poll.voted_text;
        renderPollBody(res.poll);
        if (window.TechTrek && window.TechTrek.showToast) window.TechTrek.showToast('Vote recorded.', 'success', 3000);
      }
    }).catch(function() {
      voteBtn.disabled = false;
      if (window.TechTrek && window.TechTrek.showToast) window.TechTrek.showToast('Vote failed — check your connection.', 'error', 4000);
    });
  }

  voteBtn.addEventListener('click', function() {
    if (currentPollType === 'text') {
      var inp = document.getElementById('poll-popup-text-inp');
      if (inp && inp.value.trim()) submitPollVote({ text: inp.value.trim() });
    } else if (currentPollType === 'multiple_choice' || currentPollType === 'yes_no') {
      if (votedOption != null) submitPollVote({ option_id: votedOption });
    }
  });
  dismissBtn.addEventListener('click', closePollModal);
  if (backdrop) backdrop.addEventListener('click', closePollModal);

  var evtSource = null;
  var evtTimer = null;

  function onStreamMessage(e) {
    try {
      var data = JSON.parse(e.data);
      if (data.type === 'connected') return;
      if (data.type === 'alert') {
        var alertModal = document.getElementById('alert-popup-modal');
        if (alertModal) {
          var iconEl = document.getElementById('alert-popup-icon');
          var titleEl = document.getElementById('alert-popup-title');
          var eventEl = document.getElementById('alert-popup-event');
          var msgEl = document.getElementById('alert-popup-message');
          var okBtn = document.getElementById('alert-popup-ok');
          var alertBd = document.getElementById('alert-popup-backdrop');
          if (data.alert_type === 'urgent') {
            iconEl.textContent = '\u26A0\uFE0F';
            titleEl.textContent = 'Urgent Alert';
            titleEl.style.color = 'var(--red, #ef4444)';
          } else if (data.alert_type === 'warning') {
            iconEl.textContent = '\u26A0\uFE0F';
            titleEl.textContent = 'Warning';
            titleEl.style.color = 'var(--yellow, #eab308)';
          } else {
            iconEl.textContent = '\uD83D\uDD14';
            titleEl.textContent = 'Alert';
            titleEl.style.color = 'var(--cyan, #00d4ff)';
          }
          eventEl.textContent = data.event_name ? 'From: ' + data.event_name : '';
          msgEl.textContent = data.message || '';
          alertModal.style.display = 'flex';
          function closeAlertModal() {
            alertModal.style.display = 'none';
            okBtn.removeEventListener('click', closeAlertModal);
            if (alertBd) alertBd.removeEventListener('click', closeAlertModal);
          }
          okBtn.addEventListener('click', closeAlertModal);
          if (alertBd) alertBd.addEventListener('click', closeAlertModal);
        }
        return;
      }
      if (data.closed || data.is_active === false) {
        closePollModal();
        return;
      }
      if (data.poll_id && data.question) {
        if (data.session_id && window.location.pathname === '/sessions/' + data.session_id) return;
        openPollModal();
        if (data.session_id) {
          var qs = data.event_id ? '?event_id=' + data.event_id : '';
          fetch('/sessions/' + data.session_id + '/polls/active' + qs).then(function(r) { return r.json(); }).then(function(res) {
            if (res.poll) {
              res.poll.session_id = data.session_id;
              res.poll.session_title = data.session_title;
              res.poll.event_id = data.event_id;
              renderPollBody(res.poll);
            } else {
              renderPollBody(data);
            }
          }).catch(function() { renderPollBody(data); });
        } else {
          renderPollBody(data);
        }
      }
    } catch (err) {}
  }

  function openStream() {
    if (evtSource) return;
    evtSource = new EventSource('/user/poll-notifications/stream');
    evtSource.onmessage = onStreamMessage;
    evtTimer = setTimeout(function() { closeStream(); openStream(); }, 240000);
  }
  function closeStream() {
    if (evtTimer) { clearTimeout(evtTimer); evtTimer = null; }
    if (evtSource) { evtSource.close(); evtSource = null; }
  }

  openStream();
  window.addEventListener('beforeunload', closeStream);
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) closeStream(); else openStream();
  });
})();
}
