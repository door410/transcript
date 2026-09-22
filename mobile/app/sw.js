// Service Worker：讓主畫面圖示在服務還沒起來時也能開啟。
//
// 沒有它的話，點圖示而服務未啟動 = 瀏覽器的「無法連線」錯誤頁，
// 使用者完全看不出是「還在啟動」還是「壞掉了」。
const CACHE = 'ytscript-shell-v1';
const SHELL = ['/', '/tokens.css', '/manifest.json',
               '/icon-192.png', '/icon-512.png', '/icon-maskable.png'];

const WAITING_PAGE = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>啟動中</title>
<style>
  :root{color-scheme:light dark}
  body{margin:0;min-height:100vh;display:flex;align-items:center;
       justify-content:center;font-family:system-ui,-apple-system,sans-serif;
       background:#FAF9F5;color:#0D0D0D;padding:24px}
  @media (prefers-color-scheme:dark){body{background:#000;color:#F5EBD2}}
  .box{max-width:340px;text-align:center;line-height:1.7}
  h1{font-size:19px;margin:0 0 12px}
  p{font-size:15px;opacity:.75;margin:0 0 20px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
       background:currentColor;margin:0 3px;animation:b 1.2s infinite}
  .dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
  @keyframes b{0%,80%,100%{opacity:.2}40%{opacity:1}}
  code{font-size:13px;opacity:.6;display:block;margin-top:18px}
</style></head><body><div class="box">
<h1>服務啟動中</h1>
<p><span class="dot"></span><span class="dot"></span><span class="dot"></span></p>
<p>連上之後會自動進入，不用做任何事。</p>
<code id="hint">如果一直停在這裡，請從主畫面的捷徑啟動一次。</code>
</div>
<script>
var tries = 0;
(function poll(){
  tries++;
  if (tries === 12) {
    document.querySelector('h1').textContent = '服務沒有在執行';
    document.getElementById('hint').textContent =
      '請回到主畫面，點「啟動」捷徑（終端機圖示）。啟動後這個畫面會自動進入。';
  }
  fetch('/health', {cache:'no-store'})
    .then(function(r){ if(r.ok){ location.reload(); } else { setTimeout(poll, 1500); } })
    .catch(function(){ setTimeout(poll, 1500); });
})();
</script></body></html>`;

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(SHELL.map(function (u) {
      return c.add(u).catch(function () {});
    }));
  }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== CACHE; })
                         .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;

  // API 一律走網路，絕不快取（快取回應會讓工作狀態卡住）
  if (url.pathname.startsWith('/api/') || url.pathname === '/health') return;

  // 開啟頁面：先試網路（拿到最新的 ui.html），連不上就顯示等待頁
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).then(function (r) {
        const copy = r.clone();
        caches.open(CACHE).then(function (c) { c.put('/', copy); });
        return r;
      }).catch(function () {
        return new Response(WAITING_PAGE, {
          headers: { 'Content-Type': 'text/html; charset=utf-8' }
        });
      })
    );
    return;
  }

  // 樣式與圖示：先給快取，背景更新
  e.respondWith(caches.match(req).then(function (hit) {
    const net = fetch(req).then(function (r) {
      const copy = r.clone();
      caches.open(CACHE).then(function (c) { c.put(req, copy); });
      return r;
    }).catch(function () { return hit; });
    return hit || net;
  }));
});
