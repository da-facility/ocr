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

export async function pickDirectoryTarget() {
  if (!window.showDirectoryPicker) {
    throw new Error('Directory access is not available in this browser.')
  }

  const handle = await window.showDirectoryPicker({
    mode: 'readwrite',
  } as never)

  return {
    type: 'directory' as const,
    handle,
    name: handle.name,
  }
}

export async function pickFileTarget() {
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
    type: 'file' as const,
    handle,
    name: handle.name,
  }
}

export async function writeOutputFiles(
  target: OutputTarget,
  zones: Zone[],
  results: Record<string, string>,
  cache: Map<string, string>,
) {
  if (!target) {
    return 'No output target selected.'
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
