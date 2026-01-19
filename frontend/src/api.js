const API_BASE = '/api'

export async function listCameras() {
  const res = await fetch(`${API_BASE}/cameras`)
  const data = await res.json()
  return data.cameras
}

export async function listSessions() {
  const res = await fetch(`${API_BASE}/sessions`)
  const data = await res.json()
  return data.sessions
}

export async function createSession(cameraIndex, cameraName = '') {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_index: cameraIndex, camera_name: cameraName })
  })
  return res.json()
}

export async function getSession(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`)
  if (!res.ok) throw new Error('Session not found')
  return res.json()
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function updatePerspective(sessionId, points, outputSize = null) {
  const body = { points }
  if (outputSize) {
    body.output_size = outputSize
  }
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/perspective`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  return res.json()
}

export async function addColorFilter(sessionId, bgr, tolerance = [30, 30, 30]) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/color-filters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bgr, tolerance })
  })
  return res.json()
}

export async function updateColorFilter(sessionId, filterId, tolerance) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/color-filters/${filterId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tolerance })
  })
  return res.json()
}

export async function deleteColorFilter(sessionId, filterId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/color-filters/${filterId}`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function clearColorFilters(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/color-filters`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function updateMorphology(sessionId, erosionKernel, dilationKernel) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/morphology`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      erosion_kernel: erosionKernel, 
      dilation_kernel: dilationKernel 
    })
  })
  return res.json()
}

export async function pickColor(sessionId, x, y) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/pick-color`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, y })
  })
  return res.json()
}

export async function addOcrRegion(sessionId, x, y, width, height, label = '') {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/ocr-regions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, y, width, height, label })
  })
  return res.json()
}

export async function updateOcrRegion(sessionId, regionId, data) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/ocr-regions/${regionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  return res.json()
}

export async function deleteOcrRegion(sessionId, regionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/ocr-regions/${regionId}`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function clearOcrRegions(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/ocr-regions`, {
    method: 'DELETE'
  })
  return res.json()
}

export function getStreamUrl(sessionId, type) {
  return `/stream/${sessionId}/${type}`
}

export function createOcrWebSocket(sessionId, onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${sessionId}/ocr`)
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.results) {
      onMessage(data.results)
    }
  }
  
  ws.onerror = (err) => {
    console.error('WebSocket error:', err)
  }
  
  return ws
}

// ============= Glyph API =============

export async function listGlyphs(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/glyphs`)
  const data = await res.json()
  return data.glyphs
}

export async function addGlyph(sessionId, char, template, width, height) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/glyphs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ char, template, width, height })
  })
  return res.json()
}

export async function updateGlyph(sessionId, glyphId, char) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/glyphs/${glyphId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ char })
  })
  return res.json()
}

export async function deleteGlyph(sessionId, glyphId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/glyphs/${glyphId}`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function clearGlyphs(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/glyphs`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function detectGlyphs(sessionId, regionId = null, mergeVertical = false) {
  const params = new URLSearchParams()
  if (regionId) {
    params.append('region_id', regionId)
  }
  if (mergeVertical) {
    params.append('merge_vertical', 'true')
  }
  const queryString = params.toString()
  const url = `${API_BASE}/sessions/${sessionId}/detect-glyphs${queryString ? '?' + queryString : ''}`
  const res = await fetch(url)
  return res.json()
}

export async function combineGlyphs(sessionId, indices, regionId = null) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/combine-glyphs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ indices, region_id: regionId })
  })
  if (!res.ok) throw new Error('Failed to combine glyphs')
  return res.json()
}
