export type Point = {
  x: number
  y: number
}

export type Zone = {
  id: string
  label: string
  x: number
  y: number
  width: number
  height: number
  color: string
  ocrEngine?: 'glyph' | 'paddle' | 'mnist'
  lexiconGroupId?: string
}

export type ColorFilter = {
  id: string
  rgb: [number, number, number]
  hsv: [number, number, number]
  rgbTolerance: number
  hsvTolerance: number
}

export type MorphologySettings = {
  erode: number
  dilate: number
}

export type LexiconGroup = {
  id: string
  name: string
}

export type GlyphTemplate = {
  id: string
  letter: string
  groupId?: string
  width: number
  height: number
  pixels: number[]
  createdAt: number
}

export type CandidateGlyph = {
  id: string
  x: number
  y: number
  width: number
  height: number
  pixels: number[]
  normalized: number[]
  normalizedWidth: number
  normalizedHeight: number
}

export type DigitDetection = {
  x: number
  y: number
  width: number
  height: number
  label: string
}

export type ProcessedFrame = {
  width: number
  height: number
  sourceRgba: Uint8ClampedArray
  rgba: Uint8ClampedArray
  binary: Uint8ClampedArray
  timestamp: number
}

export type OutputTarget =
  | {
      id: string
      type: 'directory'
      enabled: boolean
      handle: FileSystemDirectoryHandle
      name: string
    }
  | {
      id: string
      type: 'electron-directory'
      enabled: boolean
      path: string
      name: string
    }
  | {
      id: string
      type: 'file'
      enabled: boolean
      handle: FileSystemFileHandle
      name: string
    }
  | {
      id: string
      type: 'electron-file'
      enabled: boolean
      path: string
      name: string
    }
  | {
      id: string
      type: 'webhook'
      enabled: boolean
      url: string
    }
