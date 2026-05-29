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
import { pickDirectoryTarget, pickFileTarget, writeOutputTarget } from './lib/output'
import { detectTextBoxes, ensurePaddleOcr, recognizePaddleZones } from './lib/paddle'
import type { PaddleMetrics, PaddleOcrStatus } from './lib/paddle'
import {
  clamp,
  detectCandidates,
  drawPixelsToCanvas,
  fitWithin,
  processFrame,
  recognizeDigitZone,
  recognizeZone,
  sampleColor,
} from './lib/vision'
import type {
  CandidateGlyph,
  ColorFilter,
  DigitDetection,
  GlyphTemplate,
  LexiconGroup,
  MorphologySettings,
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
  processingEnabled: 'web-rewrite:processing-enabled',
  morphology: 'web-rewrite:morphology',
  lexiconGroups: 'web-rewrite:lexicon-groups',
  selectedLexiconGroupId: 'web-rewrite:selected-lexicon-group-id',
}

const ZONE_COLORS = ['#d44d1c', '#1859c4', '#107362', '#9b3f16', '#735b08', '#8d2459']
const DEFAULT_LEXICON_GROUP_ID = 'default'
const ZONE_BORDER_WIDTH = 4
const ZONE_TAB_HEIGHT = 24
const ZONE_TAB_PADDING_X = 10
const ZONE_TAB_CHAR_WIDTH = 7.35

type SectionId = 'capture' | 'corners' | 'colors' | 'morphology' | 'zones' | 'lexicon' | 'output'
type CursorMode = 'normal' | '4corner' | 'zones'
type CameraState = 'idle' | 'granted' | 'denied' | 'disconnected'

function AccordionSection(props: {
  id: SectionId
  title: string
  active: boolean
  disabled?: boolean
  onToggle: (id: SectionId) => void
  children: JSX.Element
}) {
  return (
    <section class="accordion-section">
      <button
        class={`accordion-trigger ${props.active ? 'active' : ''}`}
        disabled={props.disabled}
        onClick={() => props.onToggle(props.id)}
      >
        <span>{props.title}</span>
        <span class="accordion-state">{props.disabled ? 'disabled' : props.active ? 'open' : 'closed'}</span>
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

function resetStoredSettings() {
  if (typeof window === 'undefined') {
    return
  }

  Object.values(STORAGE_KEYS).forEach((key) => window.localStorage.removeItem(key))
  window.location.reload()
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

function isPaddleZone(zone: Zone) {
  return zone.ocrEngine === 'paddle'
}

function isMnistZone(zone: Zone) {
  return zone.ocrEngine === 'mnist'
}

function isLexiconZone(zone: Zone) {
  return (zone.ocrEngine ?? 'glyph') === 'glyph'
}

function zoneEngineLabel(zone: Zone) {
  if (zone.ocrEngine === 'paddle') {
    return 'paddle'
  }

  if (zone.ocrEngine === 'mnist') {
    return 'mnist'
  }

  return 'lexicon'
}

function estimatedLabelWidth(text: string) {
  return Math.ceil(text.length * ZONE_TAB_CHAR_WIDTH + ZONE_TAB_PADDING_X * 2)
}

function zoneTabText(zone: Zone) {
  const withMethod = `${zone.label} · ${zoneEngineLabel(zone)}`

  return estimatedLabelWidth(withMethod) <= zone.width ? withMethod : zone.label
}

function zoneTabWidth(zone: Zone) {
  return clamp(estimatedLabelWidth(zoneTabText(zone)), 36, Math.max(36, zone.width))
}

function normalizeLexiconGroups(groups: LexiconGroup[]) {
  const normalized = groups.length > 0 ? groups : [{ id: DEFAULT_LEXICON_GROUP_ID, name: 'Default' }]
  return normalized.some((group) => group.id === DEFAULT_LEXICON_GROUP_ID)
    ? normalized
    : [{ id: DEFAULT_LEXICON_GROUP_ID, name: 'Default' }, ...normalized]
}

function normalizeLexicon(templates: GlyphTemplate[]) {
  return templates.map((template) => ({
    ...template,
    groupId: template.groupId ?? DEFAULT_LEXICON_GROUP_ID,
  }))
}

function groupName(groups: LexiconGroup[], id?: string) {
  return groups.find((group) => group.id === (id ?? DEFAULT_LEXICON_GROUP_ID))?.name ?? 'Default'
}

function resolveCursorMode(section: SectionId): CursorMode {
  if (section === 'corners') {
    return '4corner'
  }

  if (section === 'zones') {
    return 'zones'
  }

  return 'normal'
}

function describePaddleMetrics(metrics: PaddleMetrics | null) {
  if (!metrics) {
    return 'no inference yet'
  }

  const provider = metrics.runtime
    ? `${metrics.runtime.detProvider}/${metrics.runtime.recProvider}`
    : 'provider unknown'

  return `${Math.round(metrics.totalMs)}ms total · ${Math.round(metrics.detMs)}ms det · ${Math.round(metrics.recMs)}ms rec · ${metrics.recognizedCount}/${metrics.detectedBoxes} read · ${provider}`
}

function App() {
  const storedDeviceId = loadStored<string | null>(STORAGE_KEYS.deviceId, null)
  const [devices, setDevices] = createSignal<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = createSignal(storedDeviceId)
  const [activeDeviceId, setActiveDeviceId] = createSignal<string | null>(null)
  const [cameraState, setCameraState] = createSignal<CameraState>('idle')
  const [showCameraRecovery, setShowCameraRecovery] = createSignal(false)
  const [points, setPoints] = createSignal<Point[]>(loadStored<Point[]>(STORAGE_KEYS.points, []))
  const [zones, setZones] = createSignal<Zone[]>(loadStored<Zone[]>(STORAGE_KEYS.zones, []))
  const [lexiconGroups, setLexiconGroups] = createSignal<LexiconGroup[]>(
    normalizeLexiconGroups(loadStored<LexiconGroup[]>(STORAGE_KEYS.lexiconGroups, [])),
  )
  const [selectedLexiconGroupId, setSelectedLexiconGroupId] = createSignal(
    loadStored<string>(STORAGE_KEYS.selectedLexiconGroupId, DEFAULT_LEXICON_GROUP_ID),
  )
  const [lexicon, setLexicon] = createSignal<GlyphTemplate[]>(
    normalizeLexicon(loadStored<GlyphTemplate[]>(STORAGE_KEYS.lexicon, [])),
  )
  const [colorFilters, setColorFilters] = createSignal<ColorFilter[]>(
    loadStored<ColorFilter[]>(STORAGE_KEYS.colors, []),
  )
  const [processingEnabled, setProcessingEnabled] = createSignal(
    loadStored<boolean>(STORAGE_KEYS.processingEnabled, true),
  )
  const [threshold, setThreshold] = createSignal(loadStored<number>(STORAGE_KEYS.threshold, 172))
  const [invert, setInvert] = createSignal(loadStored<boolean>(STORAGE_KEYS.invert, false))
  const [morphology, setMorphology] = createSignal<MorphologySettings>(
    loadStored<MorphologySettings>(STORAGE_KEYS.morphology, { erode: 0, dilate: 0 }),
  )
  const [results, setResults] = createSignal<Record<string, string>>({})
  const [digitDetections, setDigitDetections] = createSignal<Record<string, DigitDetection[]>>({})
  const [drawMode, setDrawMode] = createSignal(false)
  const [selectedZoneId, setSelectedZoneId] = createSignal<string | null>(null)
  const [candidateGlyphs, setCandidateGlyphs] = createSignal<CandidateGlyph[]>([])
  const [candidateLetters, setCandidateLetters] = createSignal<Record<string, string>>({})
  const [outputTargets, setOutputTargets] = createSignal<OutputTarget[]>([])
  const [outputMessages, setOutputMessages] = createSignal<Record<string, string>>({})
  const [paddleStatus, setPaddleStatus] = createSignal<PaddleOcrStatus>('unloaded')
  const [paddleMessage, setPaddleMessage] = createSignal('PaddleOCR is not loaded.')
  const [paddleLoadPercent, setPaddleLoadPercent] = createSignal(0)
  const [paddleMetrics, setPaddleMetrics] = createSignal<PaddleMetrics | null>(null)
  const [frameSize, setFrameSize] = createSignal({ width: 720, height: 405 })
  const [cameraResolution, setCameraResolution] = createSignal({ width: 0, height: 0 })
  const [streamActive, setStreamActive] = createSignal(false)
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
  let recognitionInFlight = false
  let paddleRecognitionSuppressed = false
  let writingOutput = false
  let queuedOutput = false
  const lastWrittenCaches = new Map<string, Map<string, string>>()

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
  const activeOutputCount = createMemo(() => outputTargets().filter((target) => target.enabled).length)
  const cameraOnline = createMemo(
    () => cameraState() === 'granted' && streamActive() && cameraResolution().width > 0 && cameraResolution().height > 0,
  )
  const selectedDeviceAvailable = createMemo(() => {
    const selected = selectedDeviceId()
    return Boolean(selected && devices().some((device) => device.deviceId === selected))
  })
  const selectedDeviceMissing = createMemo(() => Boolean(selectedDeviceId() && !selectedDeviceAvailable()))
  const canUseCameraPicker = createMemo(() => devices().length > 0 || selectedDeviceMissing())
  const cameraStatusText = createMemo(() => {
    if (cameraOnline()) {
      return 'on'
    }

    if (cameraState() === 'disconnected' || selectedDeviceMissing()) {
      return 'disconnected'
    }

    return cameraState()
  })
  const cameraActionLabel = createMemo(() => {
    if (!selectedDeviceAvailable()) {
      return 'open'
    }

    if (cameraOnline() && activeDeviceId() === selectedDeviceId()) {
      return 'close'
    }

    if (cameraOnline() && activeDeviceId() !== selectedDeviceId()) {
      return 'switch'
    }

    return 'open'
  })
  const cursorMode = createMemo(() => resolveCursorMode(activeSection()))
  const selectedGroupTemplates = createMemo(() =>
    lexicon().filter((glyph) => (glyph.groupId ?? DEFAULT_LEXICON_GROUP_ID) === selectedLexiconGroupId()),
  )
  const selectedGroupName = createMemo(() => groupName(lexiconGroups(), selectedLexiconGroupId()))
  const paddleFrameSource = createMemo(() => (processingEnabled() ? 'processed' : 'source'))
  const supportsNativeFileOutput = createMemo(
    () =>
      typeof window !== 'undefined' &&
      (!!window.electronOutput || !!window.showDirectoryPicker || !!window.showSaveFilePicker),
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
  const stageSize = createMemo(() => {
    const host = viewerHostSize()
    const aspect = stageAspect()
    const widthFromHeight = host.height * aspect
    const heightFromWidth = host.width / aspect

    if (widthFromHeight <= host.width) {
      return {
        width: Math.max(1, Math.floor(widthFromHeight)),
        height: Math.max(1, Math.floor(host.height)),
      }
    }

    return {
      width: Math.max(1, Math.floor(host.width)),
      height: Math.max(1, Math.floor(heightFromWidth)),
    }
  })

  createEffect(() => saveStored(STORAGE_KEYS.points, points()))
  createEffect(() => saveStored(STORAGE_KEYS.zones, zones()))
  createEffect(() => saveStored(STORAGE_KEYS.lexicon, lexicon()))
  createEffect(() => saveStored(STORAGE_KEYS.lexiconGroups, lexiconGroups()))
  createEffect(() => saveStored(STORAGE_KEYS.selectedLexiconGroupId, selectedLexiconGroupId()))
  createEffect(() => saveStored(STORAGE_KEYS.threshold, threshold()))
  createEffect(() => saveStored(STORAGE_KEYS.invert, invert()))
  createEffect(() => saveStored(STORAGE_KEYS.processingEnabled, processingEnabled()))
  createEffect(() => saveStored(STORAGE_KEYS.morphology, morphology()))
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

  createEffect(() => {
    if (lexiconGroups().some((group) => group.id === selectedLexiconGroupId())) {
      return
    }

    setSelectedLexiconGroupId(lexiconGroups()[0]?.id ?? DEFAULT_LEXICON_GROUP_ID)
  })

  createEffect(() => {
    if (!cameraOnline() && activeSection() !== 'capture') {
      setActiveSection('capture')
    }
  })

  createEffect(() => {
    if (!processingEnabled() && activeSection() === 'morphology') {
      setActiveSection('colors')
    }
  })

  async function flushOutputWrites(snapshot = results()) {
    const activeTargets = outputTargets().filter((target) => target.enabled)
    if (activeTargets.length === 0) {
      return
    }

    if (writingOutput) {
      queuedOutput = true
      return
    }

    writingOutput = true

    try {
      for (const target of activeTargets) {
        const cache = lastWrittenCaches.get(target.id) ?? new Map<string, string>()
        lastWrittenCaches.set(target.id, cache)

        try {
          const message = await writeOutputTarget(target, zones(), snapshot, cache)
          setOutputMessages((current) => ({ ...current, [target.id]: message }))
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Output write failed.'
          setOutputMessages((current) => ({ ...current, [target.id]: message }))
        }
      }
    } catch (error) {
      console.error(error)
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
      return []
    }

    const allDevices = await navigator.mediaDevices.enumerateDevices()
    const cameras = allDevices.filter((device) => device.kind === 'videoinput')
    setDevices(cameras)

    if (selectedDeviceMissing()) {
      setCameraState((current) => (current === 'denied' ? current : 'disconnected'))
      return cameras
    }

    if (!selectedDeviceId() && cameras[0]) {
      setSelectedDeviceId(cameras[0].deviceId)
    }

    return cameras
  }

  async function stopStream() {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    latestFrame = null
    setStreamActive(false)
    setActiveDeviceId(null)
    setCameraResolution({ width: 0, height: 0 })
    if (video) {
      video.srcObject = null
    }
  }

  function markCameraOff() {
    if (!streamActive() && cameraResolution().width === 0 && cameraResolution().height === 0) {
      return
    }

    latestFrame = null
    setStreamActive(false)
    setCameraResolution({ width: 0, height: 0 })
  }

  function isStreamLive() {
    return Boolean(stream?.getVideoTracks().some((track) => track.readyState === 'live' && track.enabled))
  }

  async function startStream(
    deviceId = selectedDeviceId(),
    options: { showRecoveryOnFailure?: boolean } = {},
  ) {
    if (!navigator.mediaDevices?.getUserMedia) {
      return false
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
      stream.getVideoTracks().forEach((track) => {
        track.addEventListener('ended', markCameraOff)
        track.addEventListener('mute', markCameraOff)
      })
      video.srcObject = stream
      await video.play()
      const openedDeviceId = stream.getVideoTracks()[0]?.getSettings().deviceId ?? deviceId ?? null
      setActiveDeviceId(openedDeviceId)
      setCameraState('granted')
      if (!selectedDeviceId() && openedDeviceId) {
        setSelectedDeviceId(openedDeviceId)
      }
      setShowCameraRecovery(false)
      await refreshDevices()
      return true
    } catch (error) {
      setCameraState(error instanceof DOMException && error.name === 'OverconstrainedError' ? 'disconnected' : 'denied')
      if (options.showRecoveryOnFailure) {
        setShowCameraRecovery(true)
      }
      markCameraOff()
      console.error(error)
      return false
    }
  }

  function handleCameraAction() {
    if (cameraOnline() && activeDeviceId() === selectedDeviceId()) {
      void stopStream()
      return
    }

    if (selectedDeviceAvailable()) {
      void startStream(selectedDeviceId())
    }
  }

  function handleDeviceSelection(deviceId: string) {
    setSelectedDeviceId(deviceId || null)
  }

  async function retryStoredCameraSetup() {
    const cameras = await refreshDevices()
    const selected = selectedDeviceId()
    if (!selected || !cameras.some((device) => device.deviceId === selected)) {
      setCameraState('disconnected')
      setShowCameraRecovery(true)
      return
    }

    await startStream(selected, { showRecoveryOnFailure: true })
  }

  function updateCanvasSize() {
    if (!video.videoWidth || !video.videoHeight) {
      return
    }

    setCameraResolution({
      width: video.videoWidth,
      height: video.videoHeight,
    })
    setStreamActive(isStreamLive())

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

  async function runRecognition(frame: ProcessedFrame) {
    if (recognitionInFlight) {
      return
    }

    recognitionInFlight = true
    const activeZones = zones()
    const paddleZones = activeZones.filter(isPaddleZone)
    const next: Record<string, string> = {}
    const nextDigitDetections: Record<string, DigitDetection[]> = {}

    activeZones
      .filter((zone) => !isPaddleZone(zone))
      .forEach((zone) => {
        if (isMnistZone(zone)) {
          const recognized = recognizeDigitZone(frame, zone)
          next[zone.id] = recognized.text
          nextDigitDetections[zone.id] = recognized.detections
          return
        }

        next[zone.id] = recognizeZone(
          frame,
          zone,
          lexicon().filter(
            (glyph) =>
              (glyph.groupId ?? DEFAULT_LEXICON_GROUP_ID) ===
              (zone.lexiconGroupId ?? DEFAULT_LEXICON_GROUP_ID),
          ),
        )
      })

    try {
      if (paddleZones.length > 0 && !paddleRecognitionSuppressed) {
        setPaddleStatus(paddleStatus() === 'unloaded' ? 'loading' : 'running')
        setPaddleMessage(`Reading ${paddleZones.length} PaddleOCR zone${paddleZones.length === 1 ? '' : 's'}.`)

        const paddle = await recognizePaddleZones(frame, paddleZones, paddleFrameSource())
        Object.assign(next, paddle.results)
        setPaddleMetrics(paddle.metrics)
        setPaddleStatus('ready')
        setPaddleMessage('PaddleOCR ready.')
      }

      setResults(next)
      setDigitDetections(nextDigitDetections)
      if (activeOutputCount() > 0) {
        void flushOutputWrites(next)
      }
    } catch (error) {
      paddleRecognitionSuppressed = true
      setPaddleStatus('failed')
      setPaddleMessage(error instanceof Error ? error.message : 'PaddleOCR recognition failed.')
      setResults(next)
      setDigitDetections(nextDigitDetections)
    } finally {
      recognitionInFlight = false
    }
  }

  function renderLoop(now: number) {
    if (!isStreamLive()) {
      markCameraOff()
    } else if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth && video.videoHeight) {
      if (!streamActive()) {
        setStreamActive(true)
      }
      if (cameraResolution().width !== video.videoWidth || cameraResolution().height !== video.videoHeight) {
        updateCanvasSize()
      }

      if (now - lastPreviewAt >= 1000 / 12) {
        rawContext.drawImage(video, 0, 0, frameSize().width, frameSize().height)
        const sourceImage = rawContext.getImageData(0, 0, frameSize().width, frameSize().height)

        latestFrame = processFrame(
          sourceImage,
          points(),
          threshold(),
          invert(),
          processingEnabled() ? colorFilters() : [],
          processingEnabled() ? morphology() : { erode: 0, dilate: 0 },
          processingEnabled(),
        )

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

      if (latestFrame && now - lastRecognitionAt >= 1000) {
        void runRecognition(latestFrame)
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
    if (activeSection() !== 'corners') {
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
    if (index === null || activeSection() !== 'corners') {
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
    if (!showingProcessed() || !['zones', 'lexicon'].includes(activeSection())) {
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
    if (!showingProcessed() || activeSection() !== 'zones') {
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
          ocrEngine: 'glyph',
          lexiconGroupId: selectedLexiconGroupId(),
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
    if (activeSection() !== 'colors' || !latestFrame || !processingEnabled()) {
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

  function updateZoneEngine(id: string, engine: 'glyph' | 'paddle' | 'mnist') {
    paddleRecognitionSuppressed = false
    setZones(zones().map((zone) => (zone.id === id ? { ...zone, ocrEngine: engine } : zone)))
  }

  function updateZoneLexiconGroup(id: string, groupId: string) {
    setZones(zones().map((zone) => (zone.id === id ? { ...zone, lexiconGroupId: groupId } : zone)))
  }

  function removeZone(id: string) {
    setZones(zones().filter((zone) => zone.id !== id))
    if (selectedZoneId() === id) {
      setSelectedZoneId(null)
    }
  }

  async function autoDetectPaddleZones() {
    if (!latestFrame) {
      setPaddleMessage('Start the camera and wait for a processed frame before auto-detecting zones.')
      return
    }

    paddleRecognitionSuppressed = false
    setPaddleStatus(paddleStatus() === 'unloaded' ? 'loading' : 'running')
    setPaddleMessage('Running PaddleOCR detection on the current frame.')

    try {
      const detected = await detectTextBoxes(latestFrame, paddleFrameSource())
      setPaddleMetrics(detected.metrics)

      if (detected.boxes.length === 0) {
        setPaddleStatus('ready')
        setPaddleMessage('PaddleOCR found no text boxes. Existing zones were preserved.')
        return
      }

      const nextZones: Zone[] = detected.boxes.map((box, index) => ({
        id: uid('zone'),
        label: `ocr-${index + 1}`,
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        color: ZONE_COLORS[index % ZONE_COLORS.length],
        ocrEngine: 'paddle',
        lexiconGroupId: selectedLexiconGroupId(),
      }))

      setZones(nextZones)
      setSelectedZoneId(nextZones[0]?.id ?? null)
      setPaddleStatus('ready')
      setPaddleMessage(`Detected ${nextZones.length} PaddleOCR zone${nextZones.length === 1 ? '' : 's'}.`)
      void runRecognition(latestFrame)
    } catch (error) {
      setPaddleStatus('failed')
      setPaddleMessage(error instanceof Error ? error.message : 'PaddleOCR detection failed.')
    }
  }

  function clearPerspective() {
    setPoints([])
  }

  function detectGlyphsForSelectedZone() {
    if (!latestFrame || !selectedZone()) {
      setOutputMessages((current) => ({ ...current, lexicon: 'Select a zone and wait for a processed frame before detecting glyphs.' }))
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
      groupId: selectedLexiconGroupId(),
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

  function addLexiconGroup() {
    const index = lexiconGroups().length + 1
    const group = {
      id: uid('lexicon-group'),
      name: `Group ${index}`,
    }
    setLexiconGroups([...lexiconGroups(), group])
    setSelectedLexiconGroupId(group.id)
  }

  function renameLexiconGroup(id: string, name: string) {
    setLexiconGroups(
      lexiconGroups().map((group) => (group.id === id ? { ...group, name: name || 'Untitled' } : group)),
    )
  }

  function removeLexiconGroup(id: string) {
    if (id === DEFAULT_LEXICON_GROUP_ID || lexiconGroups().length <= 1) {
      return
    }

    setLexiconGroups(lexiconGroups().filter((group) => group.id !== id))
    setLexicon(lexicon().filter((glyph) => (glyph.groupId ?? DEFAULT_LEXICON_GROUP_ID) !== id))
    setZones(
      zones().map((zone) =>
        (zone.lexiconGroupId ?? DEFAULT_LEXICON_GROUP_ID) === id
          ? { ...zone, lexiconGroupId: DEFAULT_LEXICON_GROUP_ID }
          : zone,
      ),
    )
  }

  async function preloadPaddleModels() {
    if (paddleStatus() === 'ready' || paddleStatus() === 'loading') {
      return
    }

    setPaddleStatus('loading')
    setPaddleLoadPercent(2)
    setPaddleMessage('Loading PaddleOCR models on startup.')

    let syntheticPercent = 2
    const progressTimer = window.setInterval(() => {
      syntheticPercent = Math.min(94, syntheticPercent + (syntheticPercent < 70 ? 3 : 1))
      setPaddleLoadPercent((current) => Math.max(current, syntheticPercent))
    }, 350)

    try {
      await ensurePaddleOcr((progress) => {
        setPaddleLoadPercent(progress.percent)
        setPaddleMessage(progress.message)
      })
      window.clearInterval(progressTimer)
      setPaddleLoadPercent(100)
      setPaddleStatus('ready')
      setPaddleMessage('PaddleOCR models loaded on startup.')
    } catch (error) {
      window.clearInterval(progressTimer)
      setPaddleStatus('failed')
      setPaddleLoadPercent(0)
      setPaddleMessage(error instanceof Error ? error.message : 'PaddleOCR startup load failed.')
    }
  }

  function updateColorFilter(
    id: string,
    changes: Partial<Pick<ColorFilter, 'rgbTolerance' | 'hsvTolerance'>>,
  ) {
    setColorFilters(
      colorFilters().map((filter) => (filter.id === id ? { ...filter, ...changes } : filter)),
    )
  }

  function updateMorphology(changes: Partial<MorphologySettings>) {
    setMorphology({ ...morphology(), ...changes })
  }

  function removeColorFilter(id: string) {
    setColorFilters(colorFilters().filter((filter) => filter.id !== id))
  }

  async function addOutputDirectory() {
    try {
      const target = await pickDirectoryTarget(uid('output'))
      lastWrittenCaches.set(target.id, new Map<string, string>())
      setOutputTargets([...outputTargets(), target])
      setOutputMessages((current) => ({ ...current, [target.id]: `Writing one file per OCR zone into ${target.name}.` }))
      if (Object.keys(results()).length > 0) {
        void flushOutputWrites(results())
      }
    } catch (error) {
      const id = uid('output-error')
      setOutputMessages((current) => ({ ...current, [id]: error instanceof Error ? error.message : 'Directory selection failed.' }))
    }
  }

  async function addOutputFile() {
    try {
      const target = await pickFileTarget(uid('output'))
      lastWrittenCaches.set(target.id, new Map<string, string>())
      setOutputTargets([...outputTargets(), target])
      setOutputMessages((current) => ({ ...current, [target.id]: `Writing OCR output into ${target.name}.` }))
      if (Object.keys(results()).length > 0) {
        void flushOutputWrites(results())
      }
    } catch (error) {
      const id = uid('output-error')
      setOutputMessages((current) => ({ ...current, [id]: error instanceof Error ? error.message : 'File selection failed.' }))
    }
  }

  function addWebhookOutput() {
    const target: OutputTarget = {
      id: uid('output'),
      type: 'webhook',
      enabled: false,
      url: '',
    }
    setOutputTargets([...outputTargets(), target])
    setOutputMessages((current) => ({ ...current, [target.id]: 'Enter a URL, then resume.' }))
  }

  function updateWebhookUrl(id: string, url: string) {
    lastWrittenCaches.delete(id)
    setOutputTargets(
      outputTargets().map((target) => (target.id === id && target.type === 'webhook' ? { ...target, url } : target)),
    )
  }

  function toggleOutputTarget(id: string) {
    setOutputTargets(
      outputTargets().map((target) => (target.id === id ? { ...target, enabled: !target.enabled } : target)),
    )
    const target = outputTargets().find((candidate) => candidate.id === id)
    if (target?.enabled) {
      setOutputMessages((current) => ({ ...current, [id]: 'Paused.' }))
      return
    }
    setOutputMessages((current) => ({ ...current, [id]: 'Resumed.' }))
    void flushOutputWrites(results())
  }

  function removeOutputTarget(id: string) {
    setOutputTargets(outputTargets().filter((target) => target.id !== id))
    lastWrittenCaches.delete(id)
    setOutputMessages((current) => {
      const next = { ...current }
      delete next[id]
      return next
    })
  }

  function toggleSection(section: SectionId) {
    if (section !== 'capture' && !cameraOnline()) {
      setActiveSection('capture')
      return
    }

    if (section === 'morphology' && !processingEnabled()) {
      setActiveSection('colors')
      return
    }

    setActiveSection(section)
  }

  onMount(() => {
    void (async () => {
      const cameras = await refreshDevices()
      if (!storedDeviceId) {
        return
      }

      if (!cameras.some((device) => device.deviceId === storedDeviceId)) {
        setCameraState('disconnected')
        setShowCameraRecovery(true)
        return
      }

      await startStream(storedDeviceId, { showRecoveryOnFailure: true })
    })()
    void preloadPaddleModels()

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
          <span>camera {cameraStatusText()}</span>
          <span>{zones().length} zones</span>
          <span>{lexicon().length} glyphs</span>
          <span>{lexiconGroups().length} groups</span>
          <span>processing {processingEnabled() ? 'on' : 'off'}</span>
          <span>model {paddleStatus()} {paddleLoadPercent()}%</span>
          <span>outputs {activeOutputCount()}/{outputTargets().length}</span>
        </div>
      </header>

      <main class="main-grid">
        <section class="viewer-column">
          <div ref={viewerHost} class="viewer-host">
            <div
              class="viewer-stage"
              style={{
                'aspect-ratio': `${stageAspect()}`,
                width: `${stageSize().width}px`,
                height: `${stageSize().height}px`,
              }}
            >
              <Show
                when={cameraOnline()}
                fallback={
                  <div class="camera-empty-state">
                    <div class="camera-empty-icon" aria-hidden="true">
                      <span class="camera-empty-lens" />
                      <span class="camera-empty-body" />
                      <span class="camera-empty-slash" />
                    </div>
                    <strong>Camera disconnected</strong>
                    <span>Select an available camera and open it from capture.</span>
                  </div>
                }
              >
                <Show
                  when={activeSection() === 'colors'}
                  fallback={
                    <>
                      <canvas ref={mainCanvas} class="viewer-canvas" />
                      <div class="resolution-badge">
                        <span>
                          {cameraResolution().width || frameSize().width}×{cameraResolution().height || frameSize().height}
                        </span>
                        <span>view {frameSize().width}×{frameSize().height}</span>
                      </div>

                      <Show when={!showingProcessed()}>
                        <svg
                          class={`viewer-overlay cursor-${cursorMode()}`}
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
                          class={`viewer-overlay cursor-${cursorMode()}`}
                          viewBox={`0 0 ${frameSize().width} ${frameSize().height}`}
                          onPointerDown={handleProcessedPointerDown}
                          onPointerMove={handleProcessedPointerMove}
                          onPointerUp={handleProcessedPointerUp}
                        >
                          <For each={zones()}>
                            {(zone) => (
                              <g
                                class={`${selectedZoneId() === zone.id ? 'zone-group selected' : 'zone-group'} ${activeSection() === 'lexicon' ? 'clickable-zone' : ''}`}
	                              >
	                                <rect x={zone.x} y={zone.y} width={zone.width} height={zone.height} fill={`${zone.color}18`} />
	                                <rect
	                                  x={zone.x - ZONE_BORDER_WIDTH}
	                                  y={zone.y - ZONE_BORDER_WIDTH}
	                                  width={zone.width + ZONE_BORDER_WIDTH * 2}
	                                  height={ZONE_BORDER_WIDTH}
	                                  fill={zone.color}
	                                />
	                                <rect
	                                  x={zone.x - ZONE_BORDER_WIDTH}
	                                  y={zone.y - ZONE_BORDER_WIDTH}
	                                  width={ZONE_BORDER_WIDTH}
	                                  height={zone.height + ZONE_BORDER_WIDTH * 2}
	                                  fill={zone.color}
	                                />
	                                <rect
	                                  x={zone.x + zone.width}
	                                  y={zone.y - ZONE_BORDER_WIDTH}
	                                  width={ZONE_BORDER_WIDTH}
	                                  height={zone.height + ZONE_BORDER_WIDTH * 2}
	                                  fill={zone.color}
	                                />
	                                <rect
	                                  x={zone.x - ZONE_BORDER_WIDTH}
	                                  y={zone.y + zone.height}
	                                  width={zone.width + ZONE_BORDER_WIDTH * 2}
	                                  height={ZONE_BORDER_WIDTH}
	                                  fill={zone.color}
	                                />
	                                <rect
	                                  x={zone.x - ZONE_BORDER_WIDTH}
	                                  y={zone.y - ZONE_TAB_HEIGHT - ZONE_BORDER_WIDTH}
	                                  width={zoneTabWidth(zone)}
	                                  height={ZONE_TAB_HEIGHT + ZONE_BORDER_WIDTH}
	                                  fill={zone.color}
	                                />
	                                <foreignObject
	                                  x={zone.x - ZONE_BORDER_WIDTH}
	                                  y={zone.y - ZONE_TAB_HEIGHT - ZONE_BORDER_WIDTH}
	                                  width={zoneTabWidth(zone)}
	                                  height={ZONE_TAB_HEIGHT}
	                                  class="zone-tab-label"
	                                >
	                                  <div title={`${zone.label} · ${zoneEngineLabel(zone)}`}>
	                                    {zoneTabText(zone)}
	                                  </div>
	                                </foreignObject>
	                                <Show when={isMnistZone(zone)}>
                                  <For each={digitDetections()[zone.id] ?? []}>
                                    {(detection) => (
                                      <g class="digit-detection">
                                        <rect
                                          x={detection.x}
                                          y={detection.y}
                                          width={detection.width}
                                          height={detection.height}
                                        />
                                        <text x={detection.x + 3} y={Math.max(10, detection.y - 4)}>
                                          {detection.label}
                                        </text>
                                      </g>
                                    )}
                                  </For>
                                </Show>
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
              <Show when={cameraState() === 'idle' || cameraState() === 'denied'}>
                <button class="button" onClick={() => void startStream()}>
                  request camera
                </button>
              </Show>

              <div class="camera-controls">
                <label class="field camera-device-field">
                  <span>device</span>
                  <select
                    value={selectedDeviceId() ?? ''}
                    disabled={!canUseCameraPicker()}
                    onChange={(event) => handleDeviceSelection(event.currentTarget.value)}
                  >
                    <Show when={selectedDeviceMissing()}>
                      <option value={selectedDeviceId()!}>Unavailable camera</option>
                    </Show>
                    <For each={devices()}>
                      {(device) => (
                        <option value={device.deviceId}>
                          {device.label || `camera ${device.deviceId.slice(0, 6)}`}
                        </option>
                      )}
                    </For>
                  </select>
                </label>

                <button
                  class="button secondary icon-only"
                  title="Refresh cameras"
                  disabled={!canUseCameraPicker()}
                  onClick={() => void refreshDevices()}
                >
                  ↻
                </button>

                <button
                  class="button secondary camera-action"
                  disabled={!canUseCameraPicker() || !selectedDeviceAvailable()}
                  onClick={handleCameraAction}
                >
                  {cameraActionLabel()}
                </button>
              </div>

              <Show when={selectedDeviceId() && !selectedDeviceAvailable()}>
                <p>Selected camera is unavailable.</p>
              </Show>

              <div class="status-panel">
                <strong>Resolution</strong>
                <span>
                  camera {cameraResolution().width || 0}×{cameraResolution().height || 0}
                </span>
                <span>
                  processing {frameSize().width}×{frameSize().height}
                </span>
              </div>
            </div>
          </AccordionSection>

          <AccordionSection
            id="corners"
            title="corners"
            active={activeSection() === 'corners'}
            disabled={!cameraOnline()}
            onToggle={toggleSection}
          >
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

          <AccordionSection
            id="colors"
            title="colors"
            active={activeSection() === 'colors'}
            disabled={!cameraOnline()}
            onToggle={toggleSection}
          >
            <div class="stack">
              <label class="checkbox">
                <input
                  type="checkbox"
                  checked={processingEnabled()}
                  onChange={(event) => setProcessingEnabled(event.currentTarget.checked)}
                />
                <span>use color and morphology processing</span>
              </label>

              <p>Left pane is the perspective-corrected source crop. Click it to add a sampled color. Right pane is the processed mask.</p>

              <div class="control-row">
                <button
                  class="button secondary"
                  disabled={!processingEnabled() || colorFilters().length === 0}
                  onClick={() => setColorFilters([])}
                >
                  clear colors
                </button>
              </div>

              <div class={`color-list ${processingEnabled() ? '' : 'disabled-panel'}`}>
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
                          disabled={!processingEnabled()}
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
                          disabled={!processingEnabled()}
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
                  disabled={!processingEnabled()}
                  onInput={(event) => setThreshold(Number(event.currentTarget.value))}
                />
                <strong>{threshold()}</strong>
              </label>

              <label class="checkbox">
                <input
                  type="checkbox"
                  checked={invert()}
                  disabled={!processingEnabled()}
                  onChange={(event) => setInvert(event.currentTarget.checked)}
                />
                <span>treat darker pixels as ink when no colors are selected</span>
              </label>
            </div>
          </AccordionSection>

          <AccordionSection
            id="morphology"
            title="morphology"
            active={activeSection() === 'morphology'}
            disabled={!cameraOnline() || !processingEnabled()}
            onToggle={toggleSection}
          >
            <div class="stack">
              <label class="field">
                <span>erosion</span>
                <input
                  type="range"
                  min="0"
                  max="4"
                  value={morphology().erode}
                  onInput={(event) => updateMorphology({ erode: Number(event.currentTarget.value) })}
                />
                <strong>{morphology().erode}</strong>
              </label>

              <label class="field">
                <span>dilation</span>
                <input
                  type="range"
                  min="0"
                  max="4"
                  value={morphology().dilate}
                  onInput={(event) => updateMorphology({ dilate: Number(event.currentTarget.value) })}
                />
                <strong>{morphology().dilate}</strong>
              </label>
            </div>
          </AccordionSection>

          <AccordionSection
            id="zones"
            title="zones"
            active={activeSection() === 'zones'}
            disabled={!cameraOnline()}
            onToggle={toggleSection}
          >
            <div class="stack">
              <div class="control-row">
                <button class={`button ${drawMode() ? 'active' : ''}`} onClick={() => setDrawMode(!drawMode())}>
                  {drawMode() ? 'drawing' : 'new zone'}
                </button>
                <button
                  class="button secondary"
                  disabled={paddleStatus() === 'loading' || paddleStatus() === 'running'}
                  onClick={() => void autoDetectPaddleZones()}
                >
                  auto-detect zones
                </button>
                <span>{zones().length} live</span>
              </div>

              <div class={`status-panel paddle-panel ${paddleStatus() === 'failed' ? 'failed' : ''}`}>
                <strong>PaddleOCR {paddleStatus()}</strong>
                <span class="paddle-message">{paddleMessage()}</span>
                <span class="paddle-metrics">{describePaddleMetrics(paddleMetrics())}</span>
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
                      <select
                        value={zone.ocrEngine ?? 'glyph'}
                        onChange={(event) =>
                          updateZoneEngine(zone.id, event.currentTarget.value as 'glyph' | 'paddle' | 'mnist')}
                      >
                        <option value="glyph">lexicon</option>
                        <option value="paddle">paddle</option>
                        <option value="mnist">mnist</option>
                      </select>
                      <select
                        value={zone.lexiconGroupId ?? DEFAULT_LEXICON_GROUP_ID}
                        disabled={!isLexiconZone(zone)}
                        onChange={(event) => updateZoneLexiconGroup(zone.id, event.currentTarget.value)}
                      >
                        <For each={lexiconGroups()}>
                          {(group) => <option value={group.id}>{group.name}</option>}
                        </For>
                      </select>
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

          <AccordionSection
            id="lexicon"
            title="lexicon"
            active={activeSection() === 'lexicon'}
            disabled={!cameraOnline()}
            onToggle={toggleSection}
          >
            <div class="stack">
              <div class="control-row">
                <label class="field compact-field">
                  <span>scan into</span>
                  <select
                    value={selectedLexiconGroupId()}
                    onChange={(event) => setSelectedLexiconGroupId(event.currentTarget.value)}
                  >
                    <For each={lexiconGroups()}>
                      {(group) => <option value={group.id}>{group.name}</option>}
                    </For>
                  </select>
                </label>
                <button class="button" disabled={!selectedZone()} onClick={detectGlyphsForSelectedZone}>
                  detect glyphs
                </button>
                <button class="button secondary" onClick={addLexiconGroup}>
                  new group
                </button>
                <button class="button secondary" disabled={lexicon().length === 0} onClick={() => setLexicon([])}>
                  clear lexicon
                </button>
              </div>

              <p>
                {selectedZone()
                  ? `Selected zone: ${selectedZone()!.label}; scanning into ${selectedGroupName()}`
                  : 'Select a zone in the viewer before detecting glyphs.'}
              </p>

              <div class="group-list">
                <For each={lexiconGroups()}>
                  {(group) => (
                    <div class={selectedLexiconGroupId() === group.id ? 'group-item selected' : 'group-item'}>
                      <input
                        value={group.name}
                        onInput={(event) => renameLexiconGroup(group.id, event.currentTarget.value)}
                      />
                      <span>
                        {lexicon().filter((glyph) => (glyph.groupId ?? DEFAULT_LEXICON_GROUP_ID) === group.id).length}
                      </span>
                      <button
                        class="button secondary small"
                        disabled={group.id === DEFAULT_LEXICON_GROUP_ID}
                        onClick={() => removeLexiconGroup(group.id)}
                      >
                        remove
                      </button>
                    </div>
                  )}
                </For>
              </div>

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
                <For each={selectedGroupTemplates()}>
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

          <AccordionSection
            id="output"
            title="output"
            active={activeSection() === 'output'}
            disabled={!cameraOnline()}
            onToggle={toggleSection}
          >
            <div class="stack">
              <div class="output-list">
                <For each={outputTargets()}>
                  {(target, index) => (
                    <div class={`output-item ${target.enabled ? '' : 'paused'}`}>
                      <label class="floating-field">
                        <span>
                          {target.type === 'directory'
                            ? `Folders ${index() + 1} *`
                            : target.type === 'electron-directory'
                              ? `Folders ${index() + 1} *`
                            : target.type === 'file' || target.type === 'electron-file'
                              ? `Files ${index() + 1} *`
                              : `URLs ${index() + 1} *`}
                        </span>
                        <input
                          readonly={target.type !== 'webhook'}
                          value={target.type === 'webhook' ? target.url : target.name}
                          placeholder={target.type === 'webhook' ? 'https://www.example.com/ocr' : undefined}
                          onInput={(event) => updateWebhookUrl(target.id, event.currentTarget.value)}
                        />
                      </label>

                      <div class="output-actions">
                        <button class="icon-button" title={target.enabled ? 'Pause output' : 'Resume output'} onClick={() => toggleOutputTarget(target.id)}>
                          {target.enabled ? 'II' : '▶'}
                        </button>
                        <button class="icon-button danger" title="Delete output" onClick={() => removeOutputTarget(target.id)}>
                          ×
                        </button>
                      </div>

                      <span class="output-status">
                        {target.enabled ? 'live' : 'paused'} · {outputMessages()[target.id] ?? 'Waiting.'}
                      </span>
                    </div>
                  )}
                </For>

                <Show when={outputTargets().length === 0}>
                  <p>No output destinations.</p>
                </Show>
              </div>

              <div class="control-row">
                <button class="button add-button" onClick={() => void addOutputDirectory()}>
                  <span>+</span>
                  <span>Add Folder</span>
                </button>
                <button class="button add-button secondary" onClick={() => void addOutputFile()}>
                  <span>+</span>
                  <span>Add File</span>
                </button>
                <button class="button add-button secondary" onClick={addWebhookOutput}>
                  <span>+</span>
                  <span>Add URL</span>
                </button>
              </div>

              <Show when={!supportsNativeFileOutput()}>
                <p>This browser cannot open a disk file picker for live writes. Use Chrome/Edge desktop or the Windows app.</p>
              </Show>
            </div>
          </AccordionSection>
        </aside>
      </main>

      <Show when={showCameraRecovery()}>
        <div class="modal-backdrop" role="presentation">
          <section class="camera-recovery-modal" role="dialog" aria-modal="true" aria-labelledby="camera-recovery-title">
            <h2 id="camera-recovery-title">Camera setup unavailable</h2>
            <p>
              The saved camera setup could not be reopened. Plug the camera back in and refresh, or reset the stored
              app settings.
            </p>
            <div class="modal-actions">
              <button class="button danger" onClick={resetStoredSettings}>
                Reset Settings
              </button>
              <button class="button secondary" onClick={() => void retryStoredCameraSetup()}>
                Refresh
              </button>
            </div>
          </section>
        </div>
      </Show>

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
