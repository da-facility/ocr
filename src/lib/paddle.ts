import type { InitializationSummary, OcrResult, OcrResultRuntime } from '@paddleocr/paddleocr-js'
import type { ProcessedFrame, Zone } from './types'

type PaddleOcrModule = typeof import('@paddleocr/paddleocr-js')
type PaddleOcr = Awaited<ReturnType<PaddleOcrModule['PaddleOCR']['create']>>
type PaddleFrameSource = 'source' | 'processed'

export type PaddleOcrStatus = 'unloaded' | 'loading' | 'ready' | 'running' | 'failed'

export type PaddleLoadProgress = {
  percent: number
  message: string
}

export type PaddleMetrics = {
  detMs: number
  recMs: number
  totalMs: number
  detectedBoxes: number
  recognizedCount: number
  runtime: OcrResultRuntime | null
}

export type DetectedTextBox = {
  x: number
  y: number
  width: number
  height: number
  text: string
  score: number
}

let paddleOcr: PaddleOcr | null = null
let initializePromise: Promise<PaddleOcr> | null = null
let initializationSummary: InitializationSummary | null = null

function runtimeAssetPath(path: string) {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.replace(/\/?$/, '/')}${path.replace(/^\//, '')}`
}

function ortWasmPath() {
  return import.meta.env.DEV ? '/node_modules/onnxruntime-web/dist/' : runtimeAssetPath('ort/')
}

function frameToCanvas(frame: ProcessedFrame, source: PaddleFrameSource = 'source') {
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')

  if (!context) {
    throw new Error('Canvas 2D is unavailable.')
  }

  canvas.width = frame.width
  canvas.height = frame.height
  context.putImageData(
    new ImageData(Uint8ClampedArray.from(source === 'processed' ? frame.rgba : frame.sourceRgba), frame.width, frame.height),
    0,
    0,
  )

  return canvas
}

function cropZoneToCanvas(frame: ProcessedFrame, zone: Zone, source: PaddleFrameSource = 'source') {
  const x = Math.max(0, Math.min(frame.width - 1, Math.floor(zone.x)))
  const y = Math.max(0, Math.min(frame.height - 1, Math.floor(zone.y)))
  const width = Math.max(1, Math.min(frame.width - x, Math.floor(zone.width)))
  const height = Math.max(1, Math.min(frame.height - y, Math.floor(zone.height)))
  const pixels = new Uint8ClampedArray(width * height * 4)
  const sourceRgba = source === 'processed' ? frame.rgba : frame.sourceRgba

  for (let row = 0; row < height; row += 1) {
    const sourceOffset = ((y + row) * frame.width + x) * 4
    const targetOffset = row * width * 4
    pixels.set(sourceRgba.slice(sourceOffset, sourceOffset + width * 4), targetOffset)
  }

  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')

  if (!context) {
    throw new Error('Canvas 2D is unavailable.')
  }

  canvas.width = width
  canvas.height = height
  context.putImageData(new ImageData(pixels, width, height), 0, 0)

  return canvas
}

function summarizeResult(result: OcrResult | null): PaddleMetrics | null {
  if (!result) {
    return null
  }

  return {
    ...result.metrics,
    runtime: result.runtime,
  }
}

function textFromResult(result: OcrResult) {
  return result.items
    .slice()
    .sort((a, b) => {
      const ay = Math.min(...a.poly.map((point) => point[1]))
      const by = Math.min(...b.poly.map((point) => point[1]))
      const ax = Math.min(...a.poly.map((point) => point[0]))
      const bx = Math.min(...b.poly.map((point) => point[0]))

      return Math.abs(ay - by) > 12 ? ay - by : ax - bx
    })
    .map((item) => item.text.trim())
    .filter(Boolean)
    .join(' ')
}

export async function ensurePaddleOcr(onProgress?: (progress: PaddleLoadProgress) => void) {
  if (paddleOcr) {
    onProgress?.({ percent: 100, message: 'PaddleOCR models are ready.' })
    return paddleOcr
  }

  if (!initializePromise) {
    onProgress?.({ percent: 8, message: 'Loading PaddleOCR runtime.' })
    initializePromise = import('@paddleocr/paddleocr-js')
      .then(({ PaddleOCR }) => {
        onProgress?.({ percent: 24, message: 'Starting model worker.' })
        return PaddleOCR.create({
          worker: true,
          textDetectionModelName: 'PP-OCRv5_mobile_det',
          textDetectionModelAsset: {
            url: runtimeAssetPath('models/PP-OCRv5_mobile_det_onnx.tar'),
          },
          textRecognitionModelName: 'PP-OCRv5_mobile_rec',
          textRecognitionModelAsset: {
            url: runtimeAssetPath('models/PP-OCRv5_mobile_rec_onnx.tar'),
          },
          textDetectionBatchSize: 1,
          textRecognitionBatchSize: 6,
          textDetLimitSideLen: 960,
          textDetLimitType: 'max',
          ortOptions: {
            backend: 'auto',
            wasmPaths: ortWasmPath(),
            numThreads: 1,
            simd: true,
            disableWasmProxy: true,
          },
        })
      })
      .then((ocr) => {
        paddleOcr = ocr
        initializationSummary = ocr.getInitializationSummary()
        onProgress?.({ percent: 100, message: 'PaddleOCR models are ready.' })
        return ocr
      })
      .catch((error: unknown) => {
        initializePromise = null
        paddleOcr = null
        initializationSummary = null
        throw error
      })
  }

  return initializePromise
}

export function getPaddleInitializationSummary() {
  return initializationSummary
}

export async function detectTextBoxes(frame: ProcessedFrame, source: PaddleFrameSource = 'source') {
  const ocr = await ensurePaddleOcr()
  const [result] = await ocr.predict(frameToCanvas(frame, source), {
    textDetLimitSideLen: 960,
    textDetLimitType: 'max',
  })

  const boxes: DetectedTextBox[] = result.items
    .map((item) => {
      const xs = item.poly.map((point) => point[0])
      const ys = item.poly.map((point) => point[1])
      const x = Math.max(0, Math.floor(Math.min(...xs)))
      const y = Math.max(0, Math.floor(Math.min(...ys)))
      const right = Math.min(frame.width, Math.ceil(Math.max(...xs)))
      const bottom = Math.min(frame.height, Math.ceil(Math.max(...ys)))

      return {
        x,
        y,
        width: Math.max(1, right - x),
        height: Math.max(1, bottom - y),
        text: item.text,
        score: item.score,
      }
    })
    .filter((box) => box.width >= 8 && box.height >= 8)
    .sort((a, b) => (Math.abs(a.y - b.y) > 12 ? a.y - b.y : a.x - b.x))

  return {
    boxes,
    metrics: summarizeResult(result),
    summary: initializationSummary,
  }
}

export async function recognizePaddleZones(
  frame: ProcessedFrame,
  zones: Zone[],
  source: PaddleFrameSource = 'source',
) {
  const ocr = await ensurePaddleOcr()
  const crops = zones.map((zone) => cropZoneToCanvas(frame, zone, source))
  const ocrResults = await ocr.predict(crops, {
    textDetLimitSideLen: 736,
    textDetLimitType: 'max',
  })
  const results = Object.fromEntries(
    zones.map((zone, index) => [zone.id, ocrResults[index] ? textFromResult(ocrResults[index]) : '']),
  )

  return {
    results,
    metrics: summarizeResult(ocrResults[0] ?? null),
    summary: initializationSummary,
  }
}
