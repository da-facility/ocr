import type { CandidateGlyph, ColorFilter, GlyphTemplate, Point, ProcessedFrame, Zone } from './types'

type RectGlyph = {
  x: number
  y: number
  width: number
  height: number
  area: number
  pixels: Uint8ClampedArray
}

export const TEMPLATE_WIDTH = 24
export const TEMPLATE_HEIGHT = 36

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function fitWithin(width: number, height: number, maxWidth: number, maxHeight: number) {
  const scale = Math.min(maxWidth / width, maxHeight / height, 1)

  return {
    width: Math.max(240, Math.round(width * scale)),
    height: Math.max(160, Math.round(height * scale)),
  }
}

export function rgbToHsv(red: number, green: number, blue: number): [number, number, number] {
  const r = red / 255
  const g = green / 255
  const b = blue / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const delta = max - min

  let hue = 0

  if (delta !== 0) {
    if (max === r) {
      hue = ((g - b) / delta) % 6
    } else if (max === g) {
      hue = (b - r) / delta + 2
    } else {
      hue = (r - g) / delta + 4
    }
  }

  hue = Math.round(hue * 60)
  if (hue < 0) {
    hue += 360
  }

  const saturation = max === 0 ? 0 : delta / max
  const value = max

  return [hue, saturation, value]
}

function solveLinearSystem(matrix: number[][], values: number[]) {
  const size = values.length
  const augmented = matrix.map((row, index) => [...row, values[index]])

  for (let col = 0; col < size; col += 1) {
    let pivot = col

    for (let row = col + 1; row < size; row += 1) {
      if (Math.abs(augmented[row][col]) > Math.abs(augmented[pivot][col])) {
        pivot = row
      }
    }

    if (Math.abs(augmented[pivot][col]) < 1e-9) {
      return null
    }

    if (pivot !== col) {
      ;[augmented[col], augmented[pivot]] = [augmented[pivot], augmented[col]]
    }

    const factor = augmented[col][col]
    for (let inner = col; inner <= size; inner += 1) {
      augmented[col][inner] /= factor
    }

    for (let row = 0; row < size; row += 1) {
      if (row === col) {
        continue
      }

      const scale = augmented[row][col]
      for (let inner = col; inner <= size; inner += 1) {
        augmented[row][inner] -= scale * augmented[col][inner]
      }
    }
  }

  return augmented.map((row) => row[size])
}

function computeHomography(src: Point[], dst: Point[]) {
  const matrix: number[][] = []
  const values: number[] = []

  for (let index = 0; index < 4; index += 1) {
    const from = src[index]
    const to = dst[index]

    matrix.push([from.x, from.y, 1, 0, 0, 0, -to.x * from.x, -to.x * from.y])
    values.push(to.x)

    matrix.push([0, 0, 0, from.x, from.y, 1, -to.y * from.x, -to.y * from.y])
    values.push(to.y)
  }

  const solution = solveLinearSystem(matrix, values)
  if (!solution) {
    return null
  }

  return [
    [solution[0], solution[1], solution[2]],
    [solution[3], solution[4], solution[5]],
    [solution[6], solution[7], 1],
  ]
}

function applyHomography(matrix: number[][], x: number, y: number) {
  const denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
  if (Math.abs(denominator) < 1e-9) {
    return null
  }

  return {
    x: (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
    y: (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
  }
}

function sampleNearest(data: Uint8ClampedArray, width: number, height: number, x: number, y: number) {
  const sx = Math.round(x)
  const sy = Math.round(y)

  if (sx < 0 || sy < 0 || sx >= width || sy >= height) {
    return [0, 0, 0, 255] as const
  }

  const offset = (sy * width + sx) * 4
  return [data[offset], data[offset + 1], data[offset + 2], data[offset + 3]] as const
}

export function warpPerspective(
  source: ImageData,
  points: Point[],
  outputWidth: number,
  outputHeight: number,
) {
  if (points.length !== 4) {
    return source
  }

  const destination = [
    { x: 0, y: 0 },
    { x: outputWidth - 1, y: 0 },
    { x: outputWidth - 1, y: outputHeight - 1 },
    { x: 0, y: outputHeight - 1 },
  ]

  const inverse = computeHomography(destination, points)
  if (!inverse) {
    return source
  }

  const output = new Uint8ClampedArray(outputWidth * outputHeight * 4)

  for (let y = 0; y < outputHeight; y += 1) {
    for (let x = 0; x < outputWidth; x += 1) {
      const mapped = applyHomography(inverse, x, y)
      const [r, g, b, a] = mapped
        ? sampleNearest(source.data, source.width, source.height, mapped.x, mapped.y)
        : ([0, 0, 0, 255] as const)
      const offset = (y * outputWidth + x) * 4
      output[offset] = r
      output[offset + 1] = g
      output[offset + 2] = b
      output[offset + 3] = a
    }
  }

  return new ImageData(output, outputWidth, outputHeight)
}

export function processFrame(
  source: ImageData,
  points: Point[],
  threshold: number,
  invert: boolean,
  colorFilters: ColorFilter[] = [],
): ProcessedFrame {
  const transformed =
    points.length === 4 ? warpPerspective(source, points, source.width, source.height) : source
  const sourceRgba = Uint8ClampedArray.from(transformed.data)
  const rgba = new Uint8ClampedArray(transformed.width * transformed.height * 4)
  const binary = new Uint8ClampedArray(transformed.width * transformed.height)

  for (let index = 0; index < transformed.data.length; index += 4) {
    const pixelIndex = index / 4
    const red = transformed.data[index]
    const green = transformed.data[index + 1]
    const blue = transformed.data[index + 2]
    const luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    const pixelHsv = rgbToHsv(red, green, blue)

    let on = invert ? luminance <= threshold : luminance >= threshold

    if (colorFilters.length > 0) {
      on = colorFilters.some((filter) => {
        const dr = red - filter.rgb[0]
        const dg = green - filter.rgb[1]
        const db = blue - filter.rgb[2]
        const rgbDistance = Math.sqrt((dr * dr + dg * dg + db * db) / 3)

        const hueDelta = Math.min(
          Math.abs(pixelHsv[0] - filter.hsv[0]),
          360 - Math.abs(pixelHsv[0] - filter.hsv[0]),
        ) / 180
        const saturationDelta = Math.abs(pixelHsv[1] - filter.hsv[1])
        const valueDelta = Math.abs(pixelHsv[2] - filter.hsv[2])
        const hsvDistance = Math.sqrt(
          (hueDelta * hueDelta + saturationDelta * saturationDelta + valueDelta * valueDelta) / 3,
        )

        return rgbDistance <= filter.rgbTolerance && hsvDistance <= filter.hsvTolerance / 100
      })
    }

    const value = on ? 255 : 0

    binary[pixelIndex] = value
    rgba[index] = value
    rgba[index + 1] = value
    rgba[index + 2] = value
    rgba[index + 3] = 255
  }

  return {
    width: transformed.width,
    height: transformed.height,
    sourceRgba,
    rgba,
    binary,
    timestamp: performance.now(),
  }
}

export function sampleColor(frame: ProcessedFrame, x: number, y: number) {
  const px = clamp(Math.round(x), 0, frame.width - 1)
  const py = clamp(Math.round(y), 0, frame.height - 1)
  const offset = (py * frame.width + px) * 4
  const rgb: [number, number, number] = [
    frame.sourceRgba[offset],
    frame.sourceRgba[offset + 1],
    frame.sourceRgba[offset + 2],
  ]

  return {
    rgb,
    hsv: rgbToHsv(rgb[0], rgb[1], rgb[2]),
  }
}

function cropBinary(
  binary: Uint8ClampedArray,
  frameWidth: number,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  const pixels = new Uint8ClampedArray(width * height)

  for (let row = 0; row < height; row += 1) {
    const sourceOffset = (y + row) * frameWidth + x
    const targetOffset = row * width
    pixels.set(binary.slice(sourceOffset, sourceOffset + width), targetOffset)
  }

  return pixels
}

function mergeVerticalGlyphs(
  glyphs: RectGlyph[],
  binary: Uint8ClampedArray,
  width: number,
) {
  if (glyphs.length < 2) {
    return glyphs
  }

  const merged: RectGlyph[] = []
  const used = new Set<number>()

  for (let index = 0; index < glyphs.length; index += 1) {
    if (used.has(index)) {
      continue
    }

    const base = glyphs[index]
    const cluster = [base]
    const indices = [index]

    for (let inner = index + 1; inner < glyphs.length; inner += 1) {
      if (used.has(inner)) {
        continue
      }

      const next = glyphs[inner]
      const centerDelta = Math.abs(
        base.x + base.width / 2 - (next.x + next.width / 2),
      )
      const avgWidth = (base.width + next.width) / 2
      const avgHeight = (base.height + next.height) / 2
      const top = Math.min(...cluster.map((glyph) => glyph.y))
      const bottom = Math.max(...cluster.map((glyph) => glyph.y + glyph.height))

      if (centerDelta > avgWidth * 0.8) {
        continue
      }

      const gap =
        next.y >= bottom ? next.y - bottom : top >= next.y + next.height ? top - (next.y + next.height) : 0

      if (gap <= avgHeight * 2.4) {
        cluster.push(next)
        indices.push(inner)
      }
    }

    if (cluster.length === 1) {
      merged.push(base)
      used.add(index)
      continue
    }

    const minX = Math.min(...cluster.map((glyph) => glyph.x))
    const minY = Math.min(...cluster.map((glyph) => glyph.y))
    const maxX = Math.max(...cluster.map((glyph) => glyph.x + glyph.width))
    const maxY = Math.max(...cluster.map((glyph) => glyph.y + glyph.height))
    const mergedWidth = maxX - minX
    const mergedHeight = maxY - minY
    const pixels = cropBinary(binary, width, minX, minY, mergedWidth, mergedHeight)

    merged.push({
      x: minX,
      y: minY,
      width: mergedWidth,
      height: mergedHeight,
      area: cluster.reduce((sum, glyph) => sum + glyph.area, 0),
      pixels,
    })

    indices.forEach((value) => used.add(value))
  }

  return merged.sort((a, b) => a.x - b.x)
}

function detectGlyphRects(
  binary: Uint8ClampedArray,
  width: number,
  height: number,
  minArea = 12,
) {
  const visited = new Uint8Array(width * height)
  const glyphs: RectGlyph[] = []

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const start = y * width + x
      if (visited[start] || binary[start] === 0) {
        continue
      }

      const stack = [start]
      visited[start] = 1
      const points: number[] = []
      let minX = x
      let maxX = x
      let minY = y
      let maxY = y

      while (stack.length > 0) {
        const current = stack.pop()!
        const cx = current % width
        const cy = Math.floor(current / width)
        points.push(current)

        minX = Math.min(minX, cx)
        maxX = Math.max(maxX, cx)
        minY = Math.min(minY, cy)
        maxY = Math.max(maxY, cy)

        for (let dy = -1; dy <= 1; dy += 1) {
          for (let dx = -1; dx <= 1; dx += 1) {
            if (dx === 0 && dy === 0) {
              continue
            }

            const nx = cx + dx
            const ny = cy + dy

            if (nx < 0 || ny < 0 || nx >= width || ny >= height) {
              continue
            }

            const offset = ny * width + nx
            if (visited[offset] || binary[offset] === 0) {
              continue
            }

            visited[offset] = 1
            stack.push(offset)
          }
        }
      }

      if (points.length < minArea) {
        continue
      }

      const glyphWidth = maxX - minX + 1
      const glyphHeight = maxY - minY + 1
      const pixels = cropBinary(binary, width, minX, minY, glyphWidth, glyphHeight)

      glyphs.push({
        x: minX,
        y: minY,
        width: glyphWidth,
        height: glyphHeight,
        area: points.length,
        pixels,
      })
    }
  }

  return mergeVerticalGlyphs(
    glyphs.sort((a, b) => a.x - b.x),
    binary,
    width,
  )
}

export function normalizeGlyph(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  targetWidth = TEMPLATE_WIDTH,
  targetHeight = TEMPLATE_HEIGHT,
) {
  const output = new Array<number>(targetWidth * targetHeight).fill(0)
  const scale = Math.min((targetWidth - 4) / width, (targetHeight - 4) / height)
  const contentWidth = Math.max(1, Math.round(width * scale))
  const contentHeight = Math.max(1, Math.round(height * scale))
  const offsetX = Math.floor((targetWidth - contentWidth) / 2)
  const offsetY = Math.floor((targetHeight - contentHeight) / 2)

  for (let y = 0; y < contentHeight; y += 1) {
    for (let x = 0; x < contentWidth; x += 1) {
      const sourceX = clamp(Math.floor((x / contentWidth) * width), 0, width - 1)
      const sourceY = clamp(Math.floor((y / contentHeight) * height), 0, height - 1)
      const value = pixels[sourceY * width + sourceX] > 127 ? 1 : 0
      output[(offsetY + y) * targetWidth + offsetX + x] = value
    }
  }

  return output
}

function diceSimilarity(a: number[], b: number[]) {
  let overlap = 0
  let aCount = 0
  let bCount = 0

  for (let index = 0; index < a.length; index += 1) {
    const av = a[index]
    const bv = b[index]

    if (av) {
      aCount += 1
    }
    if (bv) {
      bCount += 1
    }
    if (av && bv) {
      overlap += 1
    }
  }

  if (aCount + bCount === 0) {
    return 0
  }

  return (2 * overlap) / (aCount + bCount)
}

function extractZone(zone: Zone, binary: Uint8ClampedArray, width: number, height: number) {
  const x = clamp(Math.floor(zone.x), 0, width - 1)
  const y = clamp(Math.floor(zone.y), 0, height - 1)
  const maxWidth = clamp(Math.floor(zone.width), 1, width - x)
  const maxHeight = clamp(Math.floor(zone.height), 1, height - y)

  return {
    x,
    y,
    width: maxWidth,
    height: maxHeight,
    binary: cropBinary(binary, width, x, y, maxWidth, maxHeight),
  }
}

export function detectCandidates(frame: ProcessedFrame, zone: Zone): CandidateGlyph[] {
  const region = extractZone(zone, frame.binary, frame.width, frame.height)
  const glyphs = detectGlyphRects(region.binary, region.width, region.height)

  return glyphs.map((glyph, index) => ({
    id: `${zone.id}:${index}:${glyph.x}:${glyph.y}`,
    x: region.x + glyph.x,
    y: region.y + glyph.y,
    width: glyph.width,
    height: glyph.height,
    pixels: Array.from(glyph.pixels),
    normalized: normalizeGlyph(glyph.pixels, glyph.width, glyph.height),
    normalizedWidth: TEMPLATE_WIDTH,
    normalizedHeight: TEMPLATE_HEIGHT,
  }))
}

export function recognizeZone(frame: ProcessedFrame, zone: Zone, templates: GlyphTemplate[]) {
  if (templates.length === 0) {
    return ''
  }

  const region = extractZone(zone, frame.binary, frame.width, frame.height)
  const glyphs = detectGlyphRects(region.binary, region.width, region.height)

  return glyphs
    .map((glyph) => {
      const normalized = normalizeGlyph(glyph.pixels, glyph.width, glyph.height)
      let bestScore = 0
      let bestLabel = '?'

      for (const template of templates) {
        if (template.pixels.length !== normalized.length) {
          continue
        }

        const score = diceSimilarity(normalized, template.pixels)
        if (score > bestScore) {
          bestScore = score
          bestLabel = template.letter
        }
      }

      return bestScore >= 0.42 ? bestLabel : '?'
    })
    .join('')
}

export function drawPixelsToCanvas(
  canvas: HTMLCanvasElement,
  pixels: number[],
  width: number,
  height: number,
) {
  const context = canvas.getContext('2d')
  if (!context) {
    return
  }

  canvas.width = width
  canvas.height = height

  const image = context.createImageData(width, height)
  for (let index = 0; index < pixels.length; index += 1) {
    const value = pixels[index] ? 255 : 0
    const offset = index * 4
    image.data[offset] = value
    image.data[offset + 1] = value
    image.data[offset + 2] = value
    image.data[offset + 3] = 255
  }

  context.putImageData(image, 0, 0)
}
