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
  if (window.electronOutput) {
    const selected = await window.electronOutput.pickDirectory()
    if (!selected) {
      throw new Error('Directory selection was cancelled.')
    }

    return {
      id,
      type: 'electron-directory' as const,
      enabled: true,
      path: selected.path,
      name: selected.name,
    }
  }

  if (!window.showDirectoryPicker) {
    return pickBrowserStorageDirectoryTarget(id)
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

export async function pickBrowserStorageDirectoryTarget(id: string) {
  if (!navigator.storage?.getDirectory) {
    throw new Error('Browser storage output is not available in this browser.')
  }

  const root = await navigator.storage.getDirectory()
  const handle = await root.getDirectoryHandle('ocr-output', { create: true })

  return {
    id,
    type: 'opfs-directory' as const,
    enabled: true,
    handle,
    name: 'Browser Store / ocr-output',
  }
}

export async function pickFileTarget(id: string) {
  if (window.electronOutput) {
    const selected = await window.electronOutput.pickFile()
    if (!selected) {
      throw new Error('File selection was cancelled.')
    }

    return {
      id,
      type: 'electron-file' as const,
      enabled: true,
      path: selected.path,
      name: selected.name,
    }
  }

  if (!window.showSaveFilePicker) {
    return pickBrowserStorageFileTarget(id)
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

export async function pickBrowserStorageFileTarget(id: string) {
  if (!navigator.storage?.getDirectory) {
    throw new Error('Browser storage output is not available in this browser.')
  }

  const root = await navigator.storage.getDirectory()
  const directory = await root.getDirectoryHandle('ocr-output', { create: true })
  const handle = await directory.getFileHandle('ocr-live.txt', { create: true })

  return {
    id,
    type: 'opfs-file' as const,
    enabled: true,
    handle,
    name: 'Browser Store / ocr-live.txt',
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

  const ordered = zones.map((zone) => ({
    zone,
    text: results[zone.id] ?? '',
    name: sanitizeFileName(zone.label || zone.id),
  }))

  if (target.type === 'file' || target.type === 'opfs-file' || target.type === 'electron-file') {
    const content =
      ordered.map(({ zone, text }) => `${zone.label || zone.id}: ${text}`).join('\n') || 'No OCR zones configured.'

    if (cache.get('single-file') !== content) {
      if (target.type === 'electron-file') {
        await window.electronOutput?.writeFile(target.path, content)
      } else {
        const allowed = await ensureWritePermission(target.handle)
        if (!allowed) {
          throw new Error('Write permission was denied.')
        }

        await writeFile(target.handle, content)
      }
      cache.set('single-file', content)
    }

    return target.type === 'opfs-file'
      ? 'Browser storage file updated.'
      : 'Single output file updated.'
  }

  for (const entry of ordered) {
    const fileName = `${entry.name}.txt`
    if (cache.get(fileName) === entry.text) {
      continue
    }

    if (target.type === 'electron-directory') {
      await window.electronOutput?.writeDirectoryFile(target.path, fileName, entry.text)
    } else {
      const allowed = await ensureWritePermission(target.handle)
      if (!allowed) {
        throw new Error('Write permission was denied.')
      }

      const handle = await target.handle.getFileHandle(fileName, { create: true })
      await writeFile(handle, entry.text)
    }
    cache.set(fileName, entry.text)
  }

  const summary = ordered.map(({ zone, text }) => `${zone.label || zone.id}: ${text}`).join('\n')
  const summaryName = 'ocr-live.txt'
  if (cache.get(summaryName) !== summary) {
    if (target.type === 'electron-directory') {
      await window.electronOutput?.writeDirectoryFile(target.path, summaryName, summary)
    } else {
      const allowed = await ensureWritePermission(target.handle)
      if (!allowed) {
        throw new Error('Write permission was denied.')
      }

      const summaryHandle = await target.handle.getFileHandle(summaryName, { create: true })
      await writeFile(summaryHandle, summary)
    }
    cache.set(summaryName, summary)
  }

  return target.type === 'opfs-directory'
    ? `Updated ${ordered.length + 1} files in browser storage.`
    : `Updated ${ordered.length + 1} files in ${target.name}.`
}
