const APP_CACHE_NAME = 'ocr-console-app-v3'
const MODEL_CACHE_NAME = 'ocr-console-models-v1'
const scopeUrl = new URL(self.registration.scope)
const scopePath = scopeUrl.pathname.endsWith('/') ? scopeUrl.pathname : `${scopeUrl.pathname}/`
const scopedPath = (path) => `${scopePath}${path}`.replace(/\/{2,}/g, '/')
const SHELL_ASSETS = [
  scopedPath(''),
  scopedPath('index.html'),
  scopedPath('manifest.webmanifest'),
  scopedPath('favicon.svg'),
  scopedPath('pwa-icons/icon-192.png'),
  scopedPath('pwa-icons/icon-512.png'),
  scopedPath('pwa-icons/apple-touch-icon.png'),
]
const MODEL_ASSETS = [
  scopedPath('models/PP-OCRv5_mobile_det_onnx.tar'),
  scopedPath('models/PP-OCRv5_mobile_rec_onnx.tar'),
  scopedPath('ort/ort-wasm-simd-threaded.jsep.mjs'),
  scopedPath('ort/ort-wasm-simd-threaded.jsep.wasm'),
  scopedPath('ort/ort-wasm-simd-threaded.mjs'),
  scopedPath('ort/ort-wasm-simd-threaded.wasm'),
]
const OFFLINE_ASSETS = [...SHELL_ASSETS, ...MODEL_ASSETS]

self.addEventListener('install', (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(APP_CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)),
      caches.open(MODEL_CACHE_NAME).then((cache) => cache.addAll(MODEL_ASSETS)),
    ])
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  const currentCaches = new Set([APP_CACHE_NAME, MODEL_CACHE_NAME])

  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !currentCaches.has(key)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request

  if (request.method !== 'GET') {
    return
  }

  const url = new URL(request.url)

  if (url.origin !== self.location.origin) {
    return
  }

  if (MODEL_ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.open(MODEL_CACHE_NAME).then((cache) =>
        cache.match(request).then((cached) => {
          if (cached) {
            return cached
          }

          return fetch(request).then((response) => {
            if (response.ok) {
              cache.put(request, response.clone())
            }

            return response
          })
        }),
      ),
    )
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(APP_CACHE_NAME).then((cache) => cache.put(scopedPath('index.html'), copy))
          return response
        })
        .catch(() => caches.match(scopedPath('index.html'))),
    )
    return
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const fresh = fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone()
          const cacheName = MODEL_ASSETS.includes(url.pathname) ? MODEL_CACHE_NAME : APP_CACHE_NAME
          caches.open(cacheName).then((cache) => cache.put(request, copy))
        }

        return response
      }).catch(() => cached)

      return cached || fresh
    }),
  )
})
