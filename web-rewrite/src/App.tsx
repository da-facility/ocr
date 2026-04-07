import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
} from 'solid-js'
import type { JSX } from 'solid-js'
import './App.css'
import { pickDirectoryTarget, pickFileTarget, writeOutputFiles } from './lib/output'
import {
  clamp,
  detectCandidates,
  drawPixelsToCanvas,
  fitWithin,
  processFrame,
  recognizeZone,
  sampleColor,
} from './lib/vision'
import type {
  CandidateGlyph,
  ColorFilter,
  GlyphTemplate,
  OutputTarget,
  Point,
  ProcessedFrame,
  Zone,
} from './lib/types'

const STORAGE_KEYS = {
  points: 'web-rewrite:points',
  zones: 'web-rewrite:zones',
  lexicon: 'web-rewrite:lexicon',
  threshold: 'web-rewrite:threshold',
  invert: 'web-rewrite:invert',
  deviceId: 'web-rewrite:device-id',
  colors: 'web-rewrite:colors',
}

const ZONE_COLORS = ['#d44d1c', '#1859c4', '#107362', '#9b3f16', '#735b08', '#8d2459']

type SectionId = 'capture' | 'corners' | 'colors' | 'zones' | 'lexicon' | 'output'

function AccordionSection(props: {
  id: SectionId
  title: string
  active: boolean
  onToggle: (id: SectionId) => void
  children: JSX.Element
}) {
  return (
    <section class="accordion-section">
      <button class={`accordion-trigger ${props.active ? 'active' : ''}`} onClick={() => props.onToggle(props.id)}>
        <span>{props.title}</span>
        <span class="accordion-state">{props.active ? 'open' : 'closed'}</span>
      </button>
      <Show when={props.active}>
        <div class="accordion-body">{props.children}</div>
      </Show>
    </section>
  )
}

function PixelPreview(props: {
  pixels: number[]
  width: number
  height: number
  title: string
}) {
  let canvas!: HTMLCanvasElement

  createEffect(() => {
    drawPixelsToCanvas(canvas, props.pixels, props.width, props.height)
  })

  return (
    <div class="glyph-preview">
      <canvas ref={canvas} width={props.width} height={props.height} aria-label={props.title} />
    </div>
  )
}

function loadStored<T>(key: string, fallback: T) {
  if (typeof window === 'undefined') {
    return fallback
  }

  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function saveStored(key: string, value: unknown) {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.setItem(key, JSON.stringify(value))
}

function uid(prefix: string) {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`
}

function rectFromPoints(a: Point, b: Point) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  }
}

function describeRgb(rgb: [number, number, number]) {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`
}

function describeHsv(hsv: [number, number, number]) {
  return `hsv(${Math.round(hsv[0])}, ${Math.round(hsv[1] * 100)}%, ${Math.round(hsv[2] * 100)}%)`
}

function App() {
  const [devices, setDevices] = createSignal<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = createSignal(
    loadStored<string | null>(STORAGE_KEYS.deviceId, null),
  )
  const [permissionState, setPermissionState] = createSignal<'idle' | 'granted' | 'denied'>('idle')
  const [points, setPoints] = createSignal<Point[]>(loadStored<Point[]>(STORAGE_KEYS.points, []))
  const [zones, setZones] = createSignal<Zone[]>(loadStored<Zone[]>(STORAGE_KEYS.zones, []))
  const [lexicon, setLexicon] = createSignal<GlyphTemplate[]>(
    loadStored<GlyphTemplate[]>(STORAGE_KEYS.lexicon, []),
  )
  const [colorFilters, setColorFilters] = createSignal<ColorFilter[]>(
    loadStored<ColorFilter[]>(STORAGE_KEYS.colors, []),
  )
  const [threshold, setThreshold] = createSignal(loadStored<number>(STORAGE_KEYS.threshold, 172))
  const [invert, setInvert] = createSignal(loadStored<boolean>(STORAGE_KEYS.invert, false))
  const [results, setResults] = createSignal<Record<string, string>>({})
  const [drawMode, setDrawMode] = createSignal(false)
  const [selectedZoneId, setSelectedZoneId] = createSignal<string | null>(null)
  const [candidateGlyphs, setCandidateGlyphs] = createSignal<CandidateGlyph[]>([])
  const [candidateLetters, setCandidateLetters] = createSignal<Record<string, string>>({})
  const [outputTarget, setOutputTarget] = createSignal<OutputTarget>(null)
  const [outputMessage, setOutputMessage] = createSignal('No output target selected.')
  const [frameSize, setFrameSize] = createSignal({ width: 720, height: 405 })
  const [activeSection, setActiveSection] = createSignal<SectionId>('capture')
  const [viewerHostSize, setViewerHostSize] = createSignal({ width: 960, height: 540 })

  let video!: HTMLVideoElement
  let viewerHost!: HTMLDivElement
  let mainCanvas!: HTMLCanvasElement
  let splitSourceCanvas!: HTMLCanvasElement
  let splitMaskCanvas!: HTMLCanvasElement
  let renderHandle = 0
  let stream: MediaStream | null = null
  let latestFrame: ProcessedFrame | null = null
  let lastPreviewAt = 0
  let lastRecognitionAt = 0
  let writingOutput = false
  let queuedOutput = false
  const lastWrittenCache = new Map<string, string>()

  const rawBuffer = document.createElement('canvas')
  const transformedBuffer = document.createElement('canvas')
  const processedBuffer = document.createElement('canvas')
  const rawContext = rawBuffer.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D
  const transformedContext = transformedBuffer.getContext('2d') as CanvasRenderingContext2D
  const processedContext = processedBuffer.getContext('2d') as CanvasRenderingContext2D

  const [draggingPointIndex, setDraggingPointIndex] = createSignal<number | null>(null)
  const [draftZone, setDraftZone] = createSignal<{ start: Point; current: Point } | null>(null)
  const [draggingZone, setDraggingZone] = createSignal<{
    id: string
    offsetX: number
    offsetY: number
  } | null>(null)

  const selectedZone = createMemo(() => zones().find((zone) => zone.id === selectedZoneId()) ?? null)
  const supportsFileAccess = createMemo(
    () => typeof window !== 'undefined' && (!!window.showDirectoryPicker || !!window.showSaveFilePicker),
  )
  const frameAspect = createMemo(() => frameSize().width / frameSize().height)
  const splitOrientation = createMemo<'horizontal' | 'vertical'>(() => {
    const host = viewerHostSize()
    const aspect = frameAspect()
    const horizontalPaneAspect = host.width / 2 / Math.max(1, host.height)
    const verticalPaneAspect = host.width / Math.max(1, host.height / 2)
    const score = (paneAspect: number) => Math.max(aspect / paneAspect, paneAspect / aspect)

    return score(horizontalPaneAspect) <= score(verticalPaneAspect) ? 'horizontal' : 'vertical'
  })
  const stageAspect = createMemo(() => {
    const aspect = frameAspect()
    if (activeSection() === 'colors') {
      return splitOrientation() === 'horizontal' ? aspect * 2 : aspect / 2
    }

    return aspect
  })
  const showingProcessed = createMemo(
    () => !['capture', 'corners'].includes(activeSection()),
  )

  createEffect(() => saveStored(STORAGE_KEYS.points, points()))
  createEffect(() => saveStored(STORAGE_KEYS.zones, zones()))
  createEffect(() => saveStored(STORAGE_KEYS.lexicon, lexicon()))
  createEffect(() => saveStored(STORAGE_KEYS.threshold, threshold()))
  createEffect(() => saveStored(STORAGE_KEYS.invert, invert()))
  createEffect(() => saveStored(STORAGE_KEYS.deviceId, selectedDeviceId()))
  createEffect(() => saveStored(STORAGE_KEYS.colors, colorFilters()))

  createEffect(() => {
    if (activeSection() !== 'zones') {
      setDrawMode(false)
      setDraftZone(null)
    }
  })

  createEffect(() => {
    if (!selectedZoneId()) {
      return
    }

    if (!zones().some((zone) => zone.id === selectedZoneId())) {
      setSelectedZoneId(null)
    }
  })

  async function flushOutputWrites(snapshot = results()) {
    if (!outputTarget()) {
      return
    }

    if (writingOutput) {
      queuedOutput = true
      return
    }

    writingOutput = true

    try {
      const message = await writeOutputFiles(outputTarget(), zones(), snapshot, lastWrittenCache)
      setOutputMessage(message)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to write OCR output.'
      setOutputMessage(message)
    } finally {
      writingOutput = false
      if (queuedOutput) {
        queuedOutput = false
        void flushOutputWrites(results())
      }
    }
  }

  async function refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return
    }

    const allDevices = await navigator.mediaDevices.enumerateDevices()
    const cameras = allDevices.filter((device) => device.kind === 'videoinput')
    setDevices(cameras)

    if (!selectedDeviceId() && cameras[0]) {
      setSelectedDeviceId(cameras[0].deviceId)
    }
  }

  async function stopStream() {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    if (video) {
      video.srcObject = null
    }
  }

  async function startStream(deviceId = selectedDeviceId()) {
    if (!navigator.mediaDevices?.getUserMedia) {
      return
    }

    try {
      await stopStream()
      const constraints = deviceId
        ? {
            video: {
              deviceId: { exact: deviceId },
            },
            audio: false,
          }
        : {
            video: true,
            audio: false,
          }

      stream = await navigator.mediaDevices.getUserMedia(constraints)
      video.srcObject = stream
      await video.play()
      setPermissionState('granted')
      await refreshDevices()
    } catch (error) {
      setPermissionState('denied')
      console.error(error)
    }
  }

  function updateCanvasSize() {
    if (!video.videoWidth || !video.videoHeight) {
      return
    }

    const fitted = fitWithin(video.videoWidth, video.videoHeight, 1280, 960)
    setFrameSize(fitted)
    rawBuffer.width = fitted.width
    rawBuffer.height = fitted.height
    transformedBuffer.width = fitted.width
    transformedBuffer.height = fitted.height
    processedBuffer.width = fitted.width
    processedBuffer.height = fitted.height
  }

  function ensureDisplayCanvas(target: HTMLCanvasElement) {
    const rect = target.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const width = Math.max(1, Math.round(rect.width * dpr))
    const height = Math.max(1, Math.round(rect.height * dpr))

    if (target.width !== width || target.height !== height) {
      target.width = width
      target.height = height
    }
  }

  function drawBufferCover(source: HTMLCanvasElement, target: HTMLCanvasElement) {
    ensureDisplayCanvas(target)
    const context = target.getContext('2d')
    if (!context) {
      return
    }

    const sw = source.width
    const sh = source.height
    const dw = target.width
    const dh = target.height
    const scale = Math.max(dw / sw, dh / sh)
    const drawWidth = sw * scale
    const drawHeight = sh * scale
    const offsetX = (dw - drawWidth) / 2
    const offsetY = (dh - drawHeight) / 2

    context.clearRect(0, 0, dw, dh)
    context.drawImage(source, offsetX, offsetY, drawWidth, drawHeight)
  }

  function paintBuffersToDisplays() {
    if (activeSection() === 'colors') {
      drawBufferCover(transformedBuffer, splitSourceCanvas)
      drawBufferCover(processedBuffer, splitMaskCanvas)
      return
    }

    if (showingProcessed()) {
      drawBufferCover(processedBuffer, mainCanvas)
      return
    }

    drawBufferCover(rawBuffer, mainCanvas)
  }

  function runRecognition(frame: ProcessedFrame) {
    const next = Object.fromEntries(
      zones().map((zone) => [zone.id, recognizeZone(frame, zone, lexicon())]),
    )
    setResults(next)
    if (outputTarget()) {
      void flushOutputWrites(next)
    }
  }

  function renderLoop(now: number) {
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      if (now - lastPreviewAt >= 1000 / 12) {
        rawContext.drawImage(video, 0, 0, frameSize().width, frameSize().height)
        const sourceImage = rawContext.getImageData(0, 0, frameSize().width, frameSize().height)

        latestFrame = processFrame(sourceImage, points(), threshold(), invert(), colorFilters())

        transformedContext.putImageData(
          new ImageData(Uint8ClampedArray.from(latestFrame.sourceRgba), latestFrame.width, latestFrame.height),
          0,
          0,
        )
        processedContext.putImageData(
          new ImageData(Uint8ClampedArray.from(latestFrame.rgba), latestFrame.width, latestFrame.height),
          0,
          0,
        )
        paintBuffersToDisplays()
        lastPreviewAt = now
      }

      if (latestFrame && now - lastRecognitionAt >= 500) {
        runRecognition(latestFrame)
        lastRecognitionAt = now
      }
    }

    renderHandle = window.requestAnimationFrame(renderLoop)
  }

  function mapPointerToFrame(
    event: PointerEvent & { currentTarget: SVGSVGElement },
    width: number,
    height: number,
  ) {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: clamp(((event.clientX - rect.left) / rect.width) * width, 0, width),
      y: clamp(((event.clientY - rect.top) / rect.height) * height, 0, height),
    }
  }

  function mapPointerToCoverCanvas(
    event: PointerEvent & { currentTarget: HTMLDivElement },
    sourceWidth: number,
    sourceHeight: number,
  ) {
    const rect = event.currentTarget.getBoundingClientRect()
    const relX = event.clientX - rect.left
    const relY = event.clientY - rect.top
    const scale = Math.max(rect.width / sourceWidth, rect.height / sourceHeight)
    const drawWidth = sourceWidth * scale
    const drawHeight = sourceHeight * scale
    const offsetX = (rect.width - drawWidth) / 2
    const offsetY = (rect.height - drawHeight) / 2

    return {
      x: clamp((relX - offsetX) / scale, 0, sourceWidth - 1),
      y: clamp((relY - offsetY) / scale, 0, sourceHeight - 1),
    }
  }

  function handleSourcePointerDown(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    if (showingProcessed()) {
      return
    }

    const point = mapPointerToFrame(event, frameSize().width, frameSize().height)
    const current = points()
    const hitIndex = current.findIndex(
      (candidate) => Math.hypot(candidate.x - point.x, candidate.y - point.y) <= 18,
    )

    if (hitIndex >= 0) {
      event.currentTarget.setPointerCapture(event.pointerId)
      setDraggingPointIndex(hitIndex)
      return
    }

    if (current.length >= 4) {
      return
    }

    setPoints([...current, point])
  }

  function handleSourcePointerMove(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    const index = draggingPointIndex()
    if (index === null || showingProcessed()) {
      return
    }

    const point = mapPointerToFrame(event, frameSize().width, frameSize().height)
    setPoints(points().map((candidate, candidateIndex) => (candidateIndex === index ? point : candidate)))
  }

  function handleSourcePointerUp(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setDraggingPointIndex(null)
  }

  function handleProcessedPointerDown(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    if (!showingProcessed() || activeSection() === 'colors') {
      return
    }

    const point = mapPointerToFrame(event, frameSize().width, frameSize().height)

    if (activeSection() === 'zones' && drawMode()) {
      setDraftZone({
        start: point,
        current: point,
      })
      event.currentTarget.setPointerCapture(event.pointerId)
      return
    }

    const hit = [...zones()]
      .reverse()
      .find(
        (zone) =>
          point.x >= zone.x &&
          point.x <= zone.x + zone.width &&
          point.y >= zone.y &&
          point.y <= zone.y + zone.height,
      )

    if (!hit) {
      setSelectedZoneId(null)
      return
    }

    setSelectedZoneId(hit.id)

    if (activeSection() === 'zones') {
      setDraggingZone({
        id: hit.id,
        offsetX: point.x - hit.x,
        offsetY: point.y - hit.y,
      })
      event.currentTarget.setPointerCapture(event.pointerId)
    }
  }

  function handleProcessedPointerMove(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    if (!showingProcessed() || activeSection() === 'colors') {
      return
    }

    const point = mapPointerToFrame(event, frameSize().width, frameSize().height)

    if (draftZone()) {
      setDraftZone({
        start: draftZone()!.start,
        current: point,
      })
      return
    }

    const dragging = draggingZone()
    if (!dragging) {
      return
    }

    setZones(
      zones().map((zone) => {
        if (zone.id !== dragging.id) {
          return zone
        }

        return {
          ...zone,
          x: clamp(point.x - dragging.offsetX, 0, frameSize().width - zone.width),
          y: clamp(point.y - dragging.offsetY, 0, frameSize().height - zone.height),
        }
      }),
    )
  }

  function handleProcessedPointerUp(event: PointerEvent & { currentTarget: SVGSVGElement }) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }

    if (draftZone()) {
      const rect = rectFromPoints(draftZone()!.start, draftZone()!.current)
      if (rect.width >= 20 && rect.height >= 16) {
        const index = zones().length
        const newZone: Zone = {
          id: uid('zone'),
          label: `zone-${index + 1}`,
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
          color: ZONE_COLORS[index % ZONE_COLORS.length],
        }
        setZones([...zones(), newZone])
        setSelectedZoneId(newZone.id)
      }

      setDrawMode(false)
      setDraftZone(null)
    }

    setDraggingZone(null)
  }

  function handleColorPick(event: PointerEvent & { currentTarget: HTMLDivElement }) {
    if (activeSection() !== 'colors' || !latestFrame) {
      return
    }

    const point = mapPointerToCoverCanvas(event, latestFrame.width, latestFrame.height)
    const picked = sampleColor(latestFrame, point.x, point.y)
    const filter: ColorFilter = {
      id: uid('color'),
      rgb: picked.rgb,
      hsv: picked.hsv,
      rgbTolerance: 42,
      hsvTolerance: 18,
    }

    setColorFilters([...colorFilters(), filter])
  }

  function updateZoneLabel(id: string, label: string) {
    setZones(zones().map((zone) => (zone.id === id ? { ...zone, label } : zone)))
  }

  function removeZone(id: string) {
    setZones(zones().filter((zone) => zone.id !== id))
    if (selectedZoneId() === id) {
      setSelectedZoneId(null)
    }
  }

  function clearPerspective() {
    setPoints([])
  }

  function detectGlyphsForSelectedZone() {
    if (!latestFrame || !selectedZone()) {
      setOutputMessage('Select a zone and wait for a processed frame before detecting glyphs.')
      return
    }

    const found = detectCandidates(latestFrame, selectedZone()!)
    setCandidateGlyphs(found)
    setCandidateLetters(Object.fromEntries(found.map((glyph) => [glyph.id, ''])))
  }

  function saveGlyphCandidate(candidate: CandidateGlyph) {
    const letter = (candidateLetters()[candidate.id] ?? '').trim()
    if (!letter) {
      return
    }

    const template: GlyphTemplate = {
      id: uid('glyph'),
      letter,
      width: candidate.normalizedWidth,
      height: candidate.normalizedHeight,
      pixels: candidate.normalized,
      createdAt: Date.now(),
    }

    setLexicon([...lexicon(), template])
    setCandidateGlyphs(candidateGlyphs().filter((glyph) => glyph.id !== candidate.id))

    const nextLetters = { ...candidateLetters() }
    delete nextLetters[candidate.id]
    setCandidateLetters(nextLetters)
  }

  function removeGlyph(id: string) {
    setLexicon(lexicon().filter((glyph) => glyph.id !== id))
  }

  function updateColorFilter(
    id: string,
    changes: Partial<Pick<ColorFilter, 'rgbTolerance' | 'hsvTolerance'>>,
  ) {
    setColorFilters(
      colorFilters().map((filter) => (filter.id === id ? { ...filter, ...changes } : filter)),
    )
  }

  function removeColorFilter(id: string) {
    setColorFilters(colorFilters().filter((filter) => filter.id !== id))
  }

  async function chooseOutputDirectory() {
    try {
      const target = await pickDirectoryTarget()
      lastWrittenCache.clear()
      setOutputTarget(target)
      setOutputMessage(`Writing one file per OCR zone into ${target.name}.`)
      if (Object.keys(results()).length > 0) {
        void flushOutputWrites(results())
      }
    } catch (error) {
      setOutputMessage(error instanceof Error ? error.message : 'Directory selection failed.')
    }
  }

  async function chooseOutputFile() {
    try {
      const target = await pickFileTarget()
      lastWrittenCache.clear()
      setOutputTarget(target)
      setOutputMessage(`Writing OCR output into ${target.name}.`)
      if (Object.keys(results()).length > 0) {
        void flushOutputWrites(results())
      }
    } catch (error) {
      setOutputMessage(error instanceof Error ? error.message : 'File selection failed.')
    }
  }

  function toggleSection(section: SectionId) {
    setActiveSection(section)
  }

  onMount(() => {
    void refreshDevices()
    void startStream()

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) {
        return
      }

      setViewerHostSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      })
    })

    resizeObserver.observe(viewerHost)
    renderHandle = window.requestAnimationFrame(renderLoop)
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices)

    onCleanup(() => {
      resizeObserver.disconnect()
    })
  })

  onCleanup(() => {
    window.cancelAnimationFrame(renderHandle)
    void stopStream()
    navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices)
  })

  return (
    <div class="shell">
      <header class="topbar">
        <div class="titleblock">
          <h1>Deskframe Reader</h1>
        </div>
        <div class="headline-status">
          <span>camera {permissionState()}</span>
          <span>{zones().length} zones</span>
          <span>{lexicon().length} glyphs</span>
          <span>{colorFilters().length} colors</span>
          <span>output {outputTarget() ? outputTarget()!.type : 'off'}</span>
        </div>
      </header>

      <main class="main-grid">
        <section class="viewer-column">
          <div ref={viewerHost} class="viewer-host">
            <div
              class="viewer-stage"
              style={{
                'aspect-ratio': `${stageAspect()}`,
              }}
            >
              <Show
                when={activeSection() === 'colors'}
                fallback={
                  <>
                    <canvas ref={mainCanvas} class="viewer-canvas" />

                    <Show when={!showingProcessed()}>
                      <svg
                        class="viewer-overlay"
                        viewBox={`0 0 ${frameSize().width} ${frameSize().height}`}
                        onPointerDown={handleSourcePointerDown}
                        onPointerMove={handleSourcePointerMove}
                        onPointerUp={handleSourcePointerUp}
                      >
                        <Show when={points().length >= 2}>
                          <polyline
                            points={points()
                              .map((point) => `${point.x},${point.y}`)
                              .join(' ')}
                            class="path-line"
                          />
                        </Show>
                        <Show when={points().length === 4}>
                          <polygon
                            points={points()
                              .map((point) => `${point.x},${point.y}`)
                              .join(' ')}
                            class="path-fill"
                          />
                        </Show>
                        <For each={points()}>
                          {(point, index) => (
                            <g>
                              <circle cx={point.x} cy={point.y} r="10" class="handle-shadow" />
                              <circle cx={point.x} cy={point.y} r="6" class="handle-core" />
                              <text x={point.x + 12} y={point.y - 10} class="overlay-label">
                                {index() + 1}
                              </text>
                            </g>
                          )}
                        </For>
                      </svg>
                    </Show>

                    <Show when={showingProcessed()}>
                      <svg
                        class="viewer-overlay"
                        viewBox={`0 0 ${frameSize().width} ${frameSize().height}`}
                        onPointerDown={handleProcessedPointerDown}
                        onPointerMove={handleProcessedPointerMove}
                        onPointerUp={handleProcessedPointerUp}
                      >
                        <For each={zones()}>
                          {(zone) => (
                            <g class={selectedZoneId() === zone.id ? 'zone-group selected' : 'zone-group'}>
                              <rect
                                x={zone.x}
                                y={zone.y}
                                width={zone.width}
                                height={zone.height}
                                fill={`${zone.color}18`}
                                stroke={zone.color}
                                stroke-width="2"
                              />
                              <rect x={zone.x} y={zone.y - 18} width="112" height="18" fill={zone.color} />
                              <text x={zone.x + 8} y={zone.y - 5} class="overlay-label invert">
                                {zone.label}
                              </text>
                            </g>
                          )}
                        </For>

                        <Show when={draftZone()}>
                          {(draft) => {
                            const rect = rectFromPoints(draft().start, draft().current)
                            return (
                              <rect
                                x={rect.x}
                                y={rect.y}
                                width={rect.width}
                                height={rect.height}
                                class="zone-draft"
                              />
                            )
                          }}
                        </Show>
                      </svg>
                    </Show>
                  </>
                }
              >
                <div class={`split-layout ${splitOrientation()}`}>
                  <div class="split-pane source-pane">
                    <canvas ref={splitSourceCanvas} class="viewer-canvas" />
                    <div class="pane-overlay source-picker" onPointerDown={handleColorPick}>
                      <span>click to add color</span>
                    </div>
                  </div>
                  <div class="split-pane">
                    <canvas ref={splitMaskCanvas} class="viewer-canvas" />
                  </div>
                </div>
              </Show>
            </div>
          </div>

          <section class="results-strip">
            <For each={zones()}>
              {(zone) => (
                <div class="result-row">
                  <span>{zone.label}</span>
                  <strong>{results()[zone.id] || '—'}</strong>
                </div>
              )}
            </For>
            <Show when={zones().length === 0}>
              <div class="result-row">
                <span>ocr</span>
                <strong>no zones</strong>
              </div>
            </Show>
          </section>
        </section>

        <aside class="controls-column">
          <AccordionSection id="capture" title="capture" active={activeSection() === 'capture'} onToggle={toggleSection}>
            <div class="stack">
              <div class="control-row">
                <button class="button" onClick={() => void startStream()}>
                  request camera
                </button>
                <button class="button secondary" onClick={() => void refreshDevices()}>
                  refresh list
                </button>
              </div>

              <label class="field">
                <span>device</span>
                <select
                  value={selectedDeviceId() ?? ''}
                  onChange={(event) => setSelectedDeviceId(event.currentTarget.value)}
                >
                  <For each={devices()}>
                    {(device) => (
                      <option value={device.deviceId}>
                        {device.label || `camera ${device.deviceId.slice(0, 6)}`}
                      </option>
                    )}
                  </For>
                </select>
              </label>

              <button class="button secondary" onClick={() => void startStream(selectedDeviceId())}>
                reconnect selected camera
              </button>
            </div>
          </AccordionSection>

          <AccordionSection id="corners" title="corners" active={activeSection() === 'corners'} onToggle={toggleSection}>
            <div class="stack">
              <p>Click up to four corners directly on the viewer. Drag an existing corner to refine.</p>
              <div class="control-row">
                <button class="button secondary" onClick={clearPerspective}>
                  clear corners
                </button>
                <span>{points().length}/4 placed</span>
              </div>
            </div>
          </AccordionSection>

          <AccordionSection id="colors" title="colors" active={activeSection() === 'colors'} onToggle={toggleSection}>
            <div class="stack">
              <p>Left pane is the perspective-corrected source crop. Click it to add a sampled color. Right pane is the processed mask.</p>

              <div class="control-row">
                <button class="button secondary" disabled={colorFilters().length === 0} onClick={() => setColorFilters([])}>
                  clear colors
                </button>
              </div>

              <div class="color-list">
                <For each={colorFilters()}>
                  {(filter) => (
                    <div class="color-item">
                      <div class="color-item-head">
                        <span class="color-swatch" style={{ 'background-color': `rgb(${filter.rgb.join(' ')})` }} />
                        <div class="color-values">
                          <strong>{describeRgb(filter.rgb)}</strong>
                          <span>{describeHsv(filter.hsv)}</span>
                        </div>
                        <button class="button secondary small" onClick={() => removeColorFilter(filter.id)}>
                          remove
                        </button>
                      </div>

                      <label class="field">
                        <span>RGB similarity</span>
                        <input
                          type="range"
                          min="0"
                          max="180"
                          value={filter.rgbTolerance}
                          onInput={(event) =>
                            updateColorFilter(filter.id, {
                              rgbTolerance: Number(event.currentTarget.value),
                            })}
                        />
                        <strong>{filter.rgbTolerance}</strong>
                      </label>

                      <label class="field">
                        <span>HSV similarity</span>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={filter.hsvTolerance}
                          onInput={(event) =>
                            updateColorFilter(filter.id, {
                              hsvTolerance: Number(event.currentTarget.value),
                            })}
                        />
                        <strong>{filter.hsvTolerance}</strong>
                      </label>
                    </div>
                  )}
                </For>
                <Show when={colorFilters().length === 0}>
                  <p>No sampled colors yet.</p>
                </Show>
              </div>

              <label class="field">
                <span>fallback threshold</span>
                <input
                  type="range"
                  min="0"
                  max="255"
                  value={threshold()}
                  onInput={(event) => setThreshold(Number(event.currentTarget.value))}
                />
                <strong>{threshold()}</strong>
              </label>

              <label class="checkbox">
                <input
                  type="checkbox"
                  checked={invert()}
                  onChange={(event) => setInvert(event.currentTarget.checked)}
                />
                <span>treat darker pixels as ink when no colors are selected</span>
              </label>
            </div>
          </AccordionSection>

          <AccordionSection id="zones" title="zones" active={activeSection() === 'zones'} onToggle={toggleSection}>
            <div class="stack">
              <div class="control-row">
                <button class={`button ${drawMode() ? 'active' : ''}`} onClick={() => setDrawMode(!drawMode())}>
                  {drawMode() ? 'drawing' : 'new zone'}
                </button>
                <span>{zones().length} live</span>
              </div>

              <div class="zone-list">
                <For each={zones()}>
                  {(zone) => (
                    <div class={selectedZoneId() === zone.id ? 'zone-item selected' : 'zone-item'}>
                      <button
                        class="zone-swatch"
                        style={{ 'background-color': zone.color }}
                        onClick={() => setSelectedZoneId(zone.id)}
                      />
                      <input
                        value={zone.label}
                        onInput={(event) => updateZoneLabel(zone.id, event.currentTarget.value)}
                      />
                      <button class="button secondary small" onClick={() => removeZone(zone.id)}>
                        delete
                      </button>
                    </div>
                  )}
                </For>
                <Show when={zones().length === 0}>
                  <p>Open this section, press “new zone”, then drag on the processed viewer.</p>
                </Show>
              </div>
            </div>
          </AccordionSection>

          <AccordionSection id="lexicon" title="lexicon" active={activeSection() === 'lexicon'} onToggle={toggleSection}>
            <div class="stack">
              <div class="control-row">
                <button class="button" disabled={!selectedZone()} onClick={detectGlyphsForSelectedZone}>
                  detect glyphs
                </button>
                <button class="button secondary" disabled={lexicon().length === 0} onClick={() => setLexicon([])}>
                  clear lexicon
                </button>
              </div>

              <p>
                {selectedZone()
                  ? `Selected zone: ${selectedZone()!.label}`
                  : 'Select a zone in the viewer before detecting glyphs.'}
              </p>

              <div class="candidate-grid">
                <For each={candidateGlyphs()}>
                  {(glyph) => (
                    <div class="candidate-card">
                      <PixelPreview
                        pixels={glyph.pixels}
                        width={glyph.width}
                        height={glyph.height}
                        title="Candidate glyph preview"
                      />
                      <input
                        placeholder="letter"
                        value={candidateLetters()[glyph.id] ?? ''}
                        onInput={(event) =>
                          setCandidateLetters({
                            ...candidateLetters(),
                            [glyph.id]: event.currentTarget.value,
                          })}
                      />
                      <button class="button secondary small" onClick={() => saveGlyphCandidate(glyph)}>
                        save glyph
                      </button>
                    </div>
                  )}
                </For>
              </div>

              <div class="saved-grid">
                <For each={lexicon()}>
                  {(glyph) => (
                    <div class="saved-card">
                      <PixelPreview pixels={glyph.pixels} width={glyph.width} height={glyph.height} title={glyph.letter} />
                      <strong>{glyph.letter}</strong>
                      <button class="button secondary small" onClick={() => removeGlyph(glyph.id)}>
                        remove
                      </button>
                    </div>
                  )}
                </For>
              </div>
            </div>
          </AccordionSection>

          <AccordionSection id="output" title="output" active={activeSection() === 'output'} onToggle={toggleSection}>
            <div class="stack">
              <Show when={supportsFileAccess()} fallback={<p>This browser does not expose the File System Access API.</p>}>
                <div class="control-row">
                  <button class="button" onClick={() => void chooseOutputDirectory()}>
                    pick folder
                  </button>
                  <button class="button secondary" onClick={() => void chooseOutputFile()}>
                    pick file
                  </button>
                </div>
              </Show>
              <p>{outputMessage()}</p>
            </div>
          </AccordionSection>
        </aside>
      </main>

      <video
        ref={video}
        class="hidden-video"
        playsinline
        muted
        onLoadedMetadata={updateCanvasSize}
      />
    </div>
  )
}

export default App
