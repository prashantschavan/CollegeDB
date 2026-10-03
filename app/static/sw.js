// Service worker: catches shares from Android's Share menu, and caches the app shell.
importScripts("/static/idb.js");

const SHELL = "saver-shell-v2";
const SHELL_FILES = ["/", "/static/style.css", "/static/app.js", "/static/idb.js",
                     "/manifest.webmanifest", "/static/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== SHELL) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  // 1) A share from WhatsApp (or any app): park it in IndexedDB, then open the app to upload it.
  if (e.request.method === "POST" && url.pathname === "/share-target") {
    e.respondWith((async () => {
      try {
        const form = await e.request.formData();
        await SaverQueue.add({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          title: form.get("title") || "",
          text: form.get("text") || "",
          url: form.get("url") || "",
          files: form.getAll("files").filter((f) => f && f.size > 0),
          created: Date.now(),
        });
        return Response.redirect("/?shared=1", 303);
      } catch (err) {
        return Response.redirect("/?share_error=1", 303);
      }
    })());
    return;
  }

  // 2) API calls always go to the network.
  if (url.pathname.startsWith("/api/") || e.request.method !== "GET") return;

  // 3) App shell: network first (so updates arrive), cache as fallback when offline.
  e.respondWith((async () => {
    try {
      const fresh = await fetch(e.request);
      if (fresh.ok) (await caches.open(SHELL)).put(e.request, fresh.clone());
      return fresh;
    } catch {
      const cached = await caches.match(e.request, { ignoreSearch: true });
      return cached || Response.error();
    }
  })());
});
