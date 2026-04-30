/**
 * AIOS Offline IndexedDB — change queue for offline-first sync.
 * Stores queued changes when the user makes edits without internet access.
 * Each entry tracks the resource, field, values, and the server version
 * the client had when the change was made (for conflict detection on sync).
 */

const AIOS_DB_NAME    = 'aios-offline';
const AIOS_DB_VERSION = 1;
const STORE_QUEUE     = 'change_queue';
const STORE_META      = 'sync_meta';

let _db = null;

function openDB() {
  if (_db) return Promise.resolve(_db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(AIOS_DB_NAME, AIOS_DB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_QUEUE)) {
        const store = db.createObjectStore(STORE_QUEUE, { keyPath: 'id' });
        store.createIndex('status',    'status',    { unique: false });
        store.createIndex('queued_at', 'queued_at', { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: 'key' });
      }
    };
    req.onsuccess = e => { _db = e.target.result; resolve(_db); };
    req.onerror   = ()  => reject(req.error);
  });
}

/**
 * Add a change to the offline queue.
 * @param {object} change - {resource_type, resource_id, field, old_value, new_value,
 *                           base_version, url, method, payload, label}
 */
async function queueChange(change) {
  const db = await openDB();
  const entry = {
    id:               crypto.randomUUID ? crypto.randomUUID() : _uuid(),
    resource_type:    change.resource_type || 'unknown',
    resource_id:      change.resource_id   || '',
    field:            change.field         || '',
    old_value:        change.old_value     || '',
    new_value:        change.new_value     || '',
    base_version:     change.base_version  || 0,
    url:              change.url           || '',
    method:           change.method        || 'POST',
    payload:          change.payload       || {},
    label:            change.label         || change.resource_type || 'Change',
    queued_at:        new Date().toISOString(),
    client_modified_at: new Date().toISOString(),
    status:           'pending',
    conflict_data:    null,
  };
  return new Promise((resolve, reject) => {
    const tx    = db.transaction(STORE_QUEUE, 'readwrite');
    const req   = tx.objectStore(STORE_QUEUE).add(entry);
    req.onsuccess = () => resolve(entry);
    req.onerror   = () => reject(req.error);
  });
}

async function getPendingChanges() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(STORE_QUEUE, 'readonly');
    const req = tx.objectStore(STORE_QUEUE).index('status').getAll('pending');
    req.onsuccess = () => resolve(req.result || []);
    req.onerror   = () => reject(req.error);
  });
}

async function getAllChanges() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE_QUEUE, 'readonly')
                  .objectStore(STORE_QUEUE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror   = () => reject(req.error);
  });
}

async function updateChange(id, updates) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx    = db.transaction(STORE_QUEUE, 'readwrite');
    const store = tx.objectStore(STORE_QUEUE);
    const getReq = store.get(id);
    getReq.onsuccess = () => {
      const record = { ...getReq.result, ...updates };
      const putReq = store.put(record);
      putReq.onsuccess = () => resolve(record);
      putReq.onerror   = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

async function markSynced(id)                 { return updateChange(id, { status: 'synced' }); }
async function markConflict(id, conflictData) { return updateChange(id, { status: 'conflict', conflict_data: conflictData }); }
async function markFailed(id, reason)         { return updateChange(id, { status: 'failed', error: reason }); }

async function clearSynced() {
  const db = await openDB();
  const all = await getAllChanges();
  const toDelete = all.filter(c => c.status === 'synced');
  if (!toDelete.length) return;
  const tx = db.transaction(STORE_QUEUE, 'readwrite');
  const store = tx.objectStore(STORE_QUEUE);
  toDelete.forEach(c => store.delete(c.id));
}

async function getPendingCount() {
  const pending = await getPendingChanges();
  return pending.length;
}

async function getConflicts() {
  const all = await getAllChanges();
  return all.filter(c => c.status === 'conflict');
}

// Meta store helpers (last-sync timestamp, etc.)
async function setMeta(key, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE_META, 'readwrite')
                  .objectStore(STORE_META).put({ key, value });
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

async function getMeta(key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE_META, 'readonly')
                  .objectStore(STORE_META).get(key);
    req.onsuccess = () => resolve(req.result?.value ?? null);
    req.onerror   = () => reject(req.error);
  });
}

function _uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

// Export to window
window.AIOSOfflineDB = {
  queueChange, getPendingChanges, getAllChanges, markSynced,
  markConflict, markFailed, clearSynced, getPendingCount,
  getConflicts, setMeta, getMeta,
};
