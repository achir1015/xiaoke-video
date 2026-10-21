// 小柯影音剪輯助手：離線快取（iPad／手機「加入主畫面」後沒有網路也能開）
// 網頁本身與 version.json 先抓網路上最新的，抓不到才用快取；圖示、字型等其他檔案先用快取。
const CACHE = 'xiaoke-video-v2';
const CORE = ['./', './index.html', './version.json', './manifest.webmanifest', './favicon.svg', './favicon-32.png', './favicon-16.png',
  './apple-touch-icon.png', './icons/icon-192.png', './icons/icon-512.png', './icons/icon-maskable-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  // 只清自己的舊快取：同一個網站（achir1015.github.io）還有小柯特效等其他工具的快取
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE && k.startsWith('xiaoke-video')).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  const fonts = /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname);
  if (!sameOrigin && !fonts) return;
  const fresh = sameOrigin && (req.mode === 'navigate' || /\/(index\.html|version\.json)?$/.test(url.pathname));
  const save = res => { if (res && (res.ok || res.type === 'opaque')) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(fresh ? url.pathname : req, copy)); } return res; };
  if (fresh) {
    // 網路優先：有網路就拿最新版（version.json 帶的查詢參數不影響快取鍵）
    e.respondWith(fetch(req).then(save).catch(() => caches.match(url.pathname).then(r => r || caches.match('./index.html'))));
  } else {
    e.respondWith(caches.match(req).then(r => r || fetch(req).then(save)));
  }
});
