/* @refresh reload */
import { For, Show, createMemo, createSignal, onCleanup } from 'solid-js'
import { render } from 'solid-js/web'
import type { OcrResult, OcrResultItem } from '@paddleocr/paddleocr-js'
import { ensurePaddleOcr } from './lib/paddle'
import './paddle-test.css'

type RunState = 'idle' | 'loading' | 'ready' | 'running' | 'failed'

function itemBounds(item: OcrResultItem) {
  const xs = item.poly.map((point) => point[0])
  const ys = item.poly.map((point) => point[1])
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  const width = Math.max(...xs) - x
  const height = Math.max(...ys) - y

  return { x, y, width, height }
}

function polyPoints(item: OcrResultItem) {
  return item.poly.map((point) => point.join(',')).join(' ')
}

function PaddleTest() {
  const [imageUrl, setImageUrl] = createSignal<string | null>(null)
  const [imageName, setImageName] = createSignal('No image loaded')
  const [imageSize, setImageSize] = createSignal({ width: 1, height: 1 })
  const [state, setState] = createSignal<RunState>('idle')
  const [status, setStatus] = createSignal('Upload or paste an image.')
  const [result, setResult] = createSignal<OcrResult | null>(null)
  const [selectedIndex, setSelectedIndex] = createSignal<number | null>(null)
  let objectUrl: string | null = null
  let imageElement!: HTMLImageElement

  const items = createMemo(() => result()?.items ?? [])
  const metricsText = createMemo(() => {
    const metrics = result()?.metrics
    const runtime = result()?.runtime
    if (!metrics) {
      return 'No run yet.'
    }

    const providers = runtime ? `${runtime.detProvider}/${runtime.recProvider}` : 'provider unknown'
    return `${Math.round(metrics.totalMs)}ms total · ${Math.round(metrics.detMs)}ms det · ${Math.round(metrics.recMs)}ms rec · ${metrics.recognizedCount}/${metrics.detectedBoxes} read · ${providers}`
  })

  function replaceObjectUrl(url: string | null) {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
    }

    objectUrl = url
    setImageUrl(url)
    setResult(null)
    setSelectedIndex(null)
  }

  function loadFile(file: File) {
    if (!file.type.startsWith('image/')) {
      setState('failed')
      setStatus('The selected file is not an image.')
      return
    }

    const url = URL.createObjectURL(file)
    replaceObjectUrl(url)
    setImageName(file.name || 'Pasted image')
    setState('ready')
    setStatus('Image loaded. Run PaddleOCR when ready.')
  }

  async function runPaddle() {
    const source = imageElement
    if (!imageUrl() || !source?.complete) {
      setStatus('Load an image before running PaddleOCR.')
      return
    }

    setState('running')
    setStatus('Running PaddleOCR on the loaded image.')

    try {
      const ocr = await ensurePaddleOcr((progress) => {
        setState('loading')
        setStatus(`${progress.message} ${progress.percent}%`)
      })
      setState('running')
      const [nextResult] = await ocr.predict(source, {
        textDetLimitSideLen: 960,
        textDetLimitType: 'max',
      })
      setResult(nextResult)
      setState('ready')
      setStatus(`Found ${nextResult.items.length} text item${nextResult.items.length === 1 ? '' : 's'}.`)
    } catch (error) {
      setState('failed')
      setStatus(error instanceof Error ? error.message : 'PaddleOCR failed.')
    }
  }

  function handlePaste(event: ClipboardEvent) {
    const file = Array.from(event.clipboardData?.files ?? []).find((candidate) =>
      candidate.type.startsWith('image/'),
    )
    if (file) {
      loadFile(file)
    }
  }

  onCleanup(() => {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
    }
  })

  return (
    <main class="tester-shell" onPaste={handlePaste}>
      <header class="tester-topbar">
        <div>
          <h1>PaddleOCR test bench</h1>
          <span>{status()}</span>
        </div>
        <a href="/">Main app</a>
      </header>

      <section class="tester-workspace">
        <div class="tester-stage">
          <Show
            when={imageUrl()}
            fallback={
              <label class="drop-panel">
                <input type="file" accept="image/*" onChange={(event) => event.currentTarget.files?.[0] && loadFile(event.currentTarget.files[0])} />
                <strong>Upload or paste an image</strong>
                <span>Paste from clipboard anywhere on this page.</span>
              </label>
            }
          >
            {(url) => (
              <div class="image-frame">
                <img
                  ref={imageElement}
                  src={url()}
                  alt="OCR test input"
                  onLoad={(event) =>
                    setImageSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })}
                />
                <svg class="ocr-overlay" viewBox={`0 0 ${imageSize().width} ${imageSize().height}`}>
                  <For each={items()}>
                    {(item, index) => (
                      <g
                        class={selectedIndex() === index() ? 'ocr-hit selected' : 'ocr-hit'}
                        onPointerEnter={() => setSelectedIndex(index())}
                      >
                        <polygon points={polyPoints(item)} />
                        <text x={itemBounds(item).x} y={Math.max(14, itemBounds(item).y - 6)}>
                          {index() + 1}: {item.text}
                        </text>
                      </g>
                    )}
                  </For>
                </svg>
              </div>
            )}
          </Show>
        </div>

        <aside class="tester-panel">
          <div class="panel-actions">
            <label class="button file-button">
              <input type="file" accept="image/*" onChange={(event) => event.currentTarget.files?.[0] && loadFile(event.currentTarget.files[0])} />
              Choose Image
            </label>
            <button class="button primary" disabled={!imageUrl() || state() === 'loading' || state() === 'running'} onClick={() => void runPaddle()}>
              Run Paddle
            </button>
          </div>

          <div class={`status-card ${state() === 'failed' ? 'failed' : ''}`}>
            <strong>{imageName()}</strong>
            <span>{imageSize().width} x {imageSize().height}</span>
            <span>{metricsText()}</span>
          </div>

          <div class="result-list">
            <For each={items()}>
              {(item, index) => {
                const bounds = itemBounds(item)
                return (
                  <button
                    class={selectedIndex() === index() ? 'result-row selected' : 'result-row'}
                    onClick={() => setSelectedIndex(index())}
                  >
                    <strong>{index() + 1}</strong>
                    <span>{item.text || '(blank)'}</span>
                    <small>
                      score {item.score.toFixed(3)} · x {Math.round(bounds.x)} y {Math.round(bounds.y)} · {Math.round(bounds.width)} x {Math.round(bounds.height)}
                    </small>
                  </button>
                )
              }}
            </For>
            <Show when={items().length === 0}>
              <p class="empty-results">No PaddleOCR results yet.</p>
            </Show>
          </div>
        </aside>
      </section>
    </main>
  )
}

render(() => <PaddleTest />, document.getElementById('root')!)
