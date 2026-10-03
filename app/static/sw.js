// Service worker: catches shares from Android's Share menu, and caches the app shell.
importScripts("/static/idb.js");

const SHELL = "saver-shell-v3";
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
        // Read every shared file into memory right now. Android hands over files that may stop being
        // readable later, so we never store the File handle itself.
        const files = [], seen = [];
        for (const [key, val] of form.entries()) {
          if (typeof val === "string") continue;           // only File/Blob values
          let buf = null;
          try { buf = await val.arrayBuffer(); } catch (err) { seen.push(`${key}:${val.type}:unreadable`); continue; }
          seen.push(`${key}:${val.type || "?"}:${buf.byteLength}`);
          if (buf.byteLength) files.push({ name: val.name || "shared-file", type: val.type || "application/octet-stream", data: buf });
        }
        await SaverQueue.add({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          title: form.get("title") || "",
          text: form.get("text") || "",
          url: form.get("url") || "",
          files,
          debug: `fields: ${[...new Set([...form.keys()])].join(",") || "none"}; files: ${seen.join(" | ") || "none"}`,
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
