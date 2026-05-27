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
}

export type ColorFilter = {
  id: string
  rgb: [number, number, number]
  hsv: [number, number, number]
  rgbTolerance: number
  hsvTolerance: number
}

export type GlyphTemplate = {
  id: string
  letter: string
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
      type: 'directory'
      handle: FileSystemDirectoryHandle
      name: string
    }
  | {
      type: 'file'
      handle: FileSystemFileHandle
      name: string
    }
  | null
