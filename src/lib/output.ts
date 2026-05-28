import type { OutputTarget, Zone } from './types'

function sanitizeFileName(label: string) {
  return label
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/\s+/g, '-')
    .replace(/\.+$/, '')
    .slice(0, 80) || 'zone'
}

async function ensureWritePermission(handle: FileSystemDirectoryHandle | FileSystemFileHandle) {
  if (!handle.requestPermission) {
    return true
  }

  const descriptor = { mode: 'readwrite' as const }
  const current = (await handle.queryPermission?.(descriptor)) ?? 'prompt'
  if (current === 'granted') {
    return true
  }

  return (await handle.requestPermission(descriptor)) === 'granted'
}

async function writeFile(handle: FileSystemFileHandle, content: string) {
  const writable = await handle.createWritable()
  await writable.write(content)
  await writable.close()
}

export async function pickDirectoryTarget(id: string) {
  if (!window.showDirectoryPicker) {
    throw new Error('Directory access is not available in this browser.')
  }

  const handle = await window.showDirectoryPicker({
    mode: 'readwrite',
  } as never)

  return {
    id,
    type: 'directory' as const,
    enabled: true,
    handle,
    name: handle.name,
  }
}

export async function pickFileTarget(id: string) {
  if (!window.showSaveFilePicker) {
    throw new Error('File access is not available in this browser.')
  }

  const handle = await window.showSaveFilePicker({
    suggestedName: 'ocr-live.txt',
    types: [
      {
        description: 'Text file',
        accept: {
          'text/plain': ['.txt'],
        },
      },
    ],
  } as never)

  return {
    id,
    type: 'file' as const,
    enabled: true,
    handle,
    name: handle.name,
  }
}

function serializeOutput(zones: Zone[], results: Record<string, string>) {
  return {
    timestamp: new Date().toISOString(),
    zones: zones.map((zone) => ({
      id: zone.id,
      label: zone.label,
      text: results[zone.id] ?? '',
    })),
  }
}

export async function writeOutputTarget(
  target: OutputTarget,
  zones: Zone[],
  results: Record<string, string>,
  cache: Map<string, string>,
) {
  if (!target.enabled) {
    return 'Paused.'
  }

  if (target.type === 'webhook') {
    const url = target.url.trim()
    if (!url) {
      return 'URL required.'
    }

    const payload = JSON.stringify(serializeOutput(zones, results))
    if (cache.get('payload') === payload) {
      return 'No changes to send.'
    }

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
      },
      body: payload,
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    cache.set('payload', payload)
    return 'Sent.'
  }

  const allowed = await ensureWritePermission(target.handle)
  if (!allowed) {
    throw new Error('Write permission was denied.')
  }

  const ordered = zones.map((zone) => ({
    zone,
    text: results[zone.id] ?? '',
    name: sanitizeFileName(zone.label || zone.id),
  }))

  if (target.type === 'file') {
    const content =
      ordered.map(({ zone, text }) => `${zone.label || zone.id}: ${text}`).join('\n') || 'No OCR zones configured.'

    if (cache.get('single-file') !== content) {
      await writeFile(target.handle, content)
      cache.set('single-file', content)
    }

    return 'Single output file updated.'
  }

  for (const entry of ordered) {
    const fileName = `${entry.name}.txt`
    if (cache.get(fileName) === entry.text) {
      continue
    }

    const handle = await target.handle.getFileHandle(fileName, { create: true })
    await writeFile(handle, entry.text)
    cache.set(fileName, entry.text)
  }

  const summary = ordered.map(({ zone, text }) => `${zone.label || zone.id}: ${text}`).join('\n')
  const summaryName = 'ocr-live.txt'
  if (cache.get(summaryName) !== summary) {
    const summaryHandle = await target.handle.getFileHandle(summaryName, { create: true })
    await writeFile(summaryHandle, summary)
    cache.set(summaryName, summary)
  }

  return `Updated ${ordered.length + 1} files in ${target.name}.`
}
