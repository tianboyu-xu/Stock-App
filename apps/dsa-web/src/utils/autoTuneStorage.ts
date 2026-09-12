// Full research results can exceed localStorage's quota. IndexedDB stores the
// complete structured payload; memory also preserves a result during navigation.
const current = new Map<string, unknown>();
let pendingWrite: Promise<void> = Promise.resolve();

export function clearAutoTuneSessionCache(): void {
  current.clear();
}

export function peekAutoTuneState<T>(key: string): T | null {
  return (current.get(key) as T | undefined) ?? null;
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('dsa-auto-tune', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('results');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function readAutoTuneState<T>(key: string, legacy: () => T | null): Promise<T | null> {
  if (current.has(key)) return current.get(key) as T;
  try {
    const db = await database();
    const value = await new Promise<T | undefined>((resolve, reject) => {
      const request = db.transaction('results').objectStore('results').get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    }).finally(() => db.close());
    // A tune may have completed while the database read was pending.
    if (current.has(key)) return current.get(key) as T;
    if (value !== undefined) {
      current.set(key, value);
      return value;
    }
  } catch {
    // Browsers with storage disabled may still have a readable legacy cache.
  }
  const value = legacy();
  if (value !== null) current.set(key, value);
  return value;
}

export function writeAutoTuneState<T>(key: string, value: T): Promise<void> {
  current.set(key, value);
  const write = pendingWrite.catch(() => undefined).then(() => persist(key, value));
  pendingWrite = write;
  return write;
}

async function persist<T>(key: string, value: T): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction('results', 'readwrite');
      transaction.objectStore('results').put(value, key);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}
