// Tiny IndexedDB queue shared by the service worker and the page.
// Shares are parked here first, so nothing is lost if the server is asleep or the network drops.
const SaverQueue = (() => {
  const DB = "saver", STORE = "shares";
  const open = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  const tx = async (mode, fn) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const out = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(out && "result" in out ? out.result : undefined);
      t.onerror = () => reject(t.error);
    });
  };
  return {
    add: (entry) => tx("readwrite", (s) => s.put(entry)),
    all: () => tx("readonly", (s) => s.getAll()),
    remove: (id) => tx("readwrite", (s) => s.delete(id)),
  };
})();
