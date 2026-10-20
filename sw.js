const CACHE='pohang-matjip-v10';
const CORE=['./','index.html','manifest.webmanifest','placeholder.svg','icon-192.png','icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url); if(u.origin!==location.origin||e.request.method!=='GET') return;
  const key=u.origin+u.pathname;  // ?t= 캐시버스터는 무시하고 파일당 1개만 보관(오프라인 대비)
  // 데이터(.json)와 화면(HTML)은 항상 네트워크 먼저, 캐시 안 씀(no-store). 실패할 때만 저장본
  if(u.pathname.endsWith('.json')||e.request.mode==='navigate'||u.pathname.endsWith('/')||u.pathname.endsWith('.html')){
    e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{if(r.ok){const c=r.clone();caches.open(CACHE).then(x=>x.put(key,c));}return r;})
      .catch(()=>caches.match(key).then(m=>m||caches.match('index.html'))));return;}
  e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{if(r.ok){const c=r.clone();caches.open(CACHE).then(x=>x.put(e.request,c));}return r;})));
});
