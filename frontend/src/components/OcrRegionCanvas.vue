<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  regions: {
    type: Array,
    default: () => []
  },
  frameSize: {
    type: Array,
    default: () => [800, 600]
  }
})

const emit = defineEmits(['add-region', 'update-region'])

const container = ref(null)
const isDrawing = ref(false)
const drawStart = ref(null)
const drawEnd = ref(null)
const draggingRegion = ref(null)
const dragOffset = ref({ x: 0, y: 0 })
const localRegions = ref([])
const videoBounds = ref({ x: 0, y: 0, width: 0, height: 0 })

const colors = ['#00d9ff', '#00ff9d', '#ff6b6b', '#ffb347', '#c084fc', '#f472b6']

watch(() => props.regions, (newRegions) => {
  if (!draggingRegion.value) {
    localRegions.value = newRegions.map(r => ({ ...r }))
  }
}, { immediate: true, deep: true })

function getColor(index) {
  return colors[index % colors.length]
}

function updateVideoBounds() {
  if (!container.value) return
  
  // Find the video/img element in the sibling StreamViewer
  const parent = container.value.parentElement
  const img = parent?.querySelector('img')
  
  if (img && img.complete) {
    const containerRect = container.value.getBoundingClientRect()
    const imgRect = img.getBoundingClientRect()
    
    videoBounds.value = {
      x: imgRect.left - containerRect.left,
      y: imgRect.top - containerRect.top,
      width: imgRect.width,
      height: imgRect.height
    }
  }
}

// Convert mouse position to frame coordinates
function getMousePos(e) {
  updateVideoBounds()
  
  if (!container.value || videoBounds.value.width === 0) return { x: 0, y: 0 }
  
  const containerRect = container.value.getBoundingClientRect()
  const mouseX = e.clientX - containerRect.left - videoBounds.value.x
  const mouseY = e.clientY - containerRect.top - videoBounds.value.y
  
  const scaleX = props.frameSize[0] / videoBounds.value.width
  const scaleY = props.frameSize[1] / videoBounds.value.height
  
  return {
    x: Math.round(mouseX * scaleX),
    y: Math.round(mouseY * scaleY)
  }
}

// Convert frame coordinates to display coordinates
function toDisplayCoords(frameX, frameY) {
  if (videoBounds.value.width === 0) return { x: 0, y: 0 }
  
  const scaleX = videoBounds.value.width / props.frameSize[0]
  const scaleY = videoBounds.value.height / props.frameSize[1]
  
  return {
    x: frameX * scaleX + videoBounds.value.x,
    y: frameY * scaleY + videoBounds.value.y,
  }
}

function toDisplaySize(w, h) {
  if (videoBounds.value.width === 0) return { width: 0, height: 0 }
  
  const scaleX = videoBounds.value.width / props.frameSize[0]
  const scaleY = videoBounds.value.height / props.frameSize[1]
  
  return {
    width: w * scaleX,
    height: h * scaleY,
  }
}

function isInsideVideo(e) {
  if (!container.value || videoBounds.value.width === 0) return false
  
  const containerRect = container.value.getBoundingClientRect()
  const mouseX = e.clientX - containerRect.left
  const mouseY = e.clientY - containerRect.top
  
  return (
    mouseX >= videoBounds.value.x &&
    mouseX <= videoBounds.value.x + videoBounds.value.width &&
    mouseY >= videoBounds.value.y &&
    mouseY <= videoBounds.value.y + videoBounds.value.height
  )
}

function findRegionAtPoint(pos) {
  for (let i = localRegions.value.length - 1; i >= 0; i--) {
    const r = localRegions.value[i]
    if (pos.x >= r.x && pos.x <= r.x + r.width && pos.y >= r.y && pos.y <= r.y + r.height) {
      return { region: r, index: i }
    }
  }
  return null
}

function handleMouseDown(e) {
  updateVideoBounds()
  
  if (!isInsideVideo(e)) return
  
  const pos = getMousePos(e)
  const found = findRegionAtPoint(pos)
  
  if (found) {
    draggingRegion.value = found.region
    dragOffset.value = { x: pos.x - found.region.x, y: pos.y - found.region.y }
    e.preventDefault()
  } else {
    isDrawing.value = true
    drawStart.value = pos
    drawEnd.value = pos
  }
}

function handleMouseMove(e) {
  const pos = getMousePos(e)
  
  if (draggingRegion.value) {
    const newX = Math.max(0, Math.min(props.frameSize[0] - draggingRegion.value.width, pos.x - dragOffset.value.x))
    const newY = Math.max(0, Math.min(props.frameSize[1] - draggingRegion.value.height, pos.y - dragOffset.value.y))
    
    draggingRegion.value.x = newX
    draggingRegion.value.y = newY
  } else if (isDrawing.value) {
    drawEnd.value = pos
  }
}

function handleMouseUp() {
  if (draggingRegion.value) {
    emit('update-region', draggingRegion.value.id, { 
      x: draggingRegion.value.x, 
      y: draggingRegion.value.y 
    })
    draggingRegion.value = null
  } else if (isDrawing.value && drawStart.value && drawEnd.value) {
    const x = Math.min(drawStart.value.x, drawEnd.value.x)
    const y = Math.min(drawStart.value.y, drawEnd.value.y)
    const width = Math.abs(drawEnd.value.x - drawStart.value.x)
    const height = Math.abs(drawEnd.value.y - drawStart.value.y)
    
    if (width > 10 && height > 10) {
      emit('add-region', x, y, width, height)
    }
  }
  
  isDrawing.value = false
  drawStart.value = null
  drawEnd.value = null
}

const drawingRect = computed(() => {
  if (!isDrawing.value || !drawStart.value || !drawEnd.value) return null
  
  const x = Math.min(drawStart.value.x, drawEnd.value.x)
  const y = Math.min(drawStart.value.y, drawEnd.value.y)
  const width = Math.abs(drawEnd.value.x - drawStart.value.x)
  const height = Math.abs(drawEnd.value.y - drawStart.value.y)
  
  const display = toDisplayCoords(x, y)
  const size = toDisplaySize(width, height)
  
  return {
    x: display.x,
    y: display.y,
    width: size.width,
    height: size.height
  }
})

let resizeObserver = null
let animationFrame = null

function scheduleUpdate() {
  if (animationFrame) cancelAnimationFrame(animationFrame)
  animationFrame = requestAnimationFrame(() => {
    updateVideoBounds()
  })
}

onMounted(() => {
  // Initial update after a short delay to let the video load
  setTimeout(updateVideoBounds, 100)
  setTimeout(updateVideoBounds, 500)
  setTimeout(updateVideoBounds, 1000)
  
  // Watch for resize
  resizeObserver = new ResizeObserver(scheduleUpdate)
  if (container.value) {
    resizeObserver.observe(container.value)
  }
  
  // Also update on window resize
  window.addEventListener('resize', scheduleUpdate)
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
  window.removeEventListener('resize', scheduleUpdate)
  if (animationFrame) cancelAnimationFrame(animationFrame)
})
</script>

<template>
  <div 
    ref="container"
    class="absolute inset-0 cursor-crosshair"
    @mousedown="handleMouseDown"
    @mousemove="handleMouseMove"
    @mouseup="handleMouseUp"
    @mouseleave="handleMouseUp"
  >
    <svg class="w-full h-full pointer-events-none">
      <defs>
        <filter id="regionGlow">
          <feGaussianBlur
            stdDeviation="2"
            result="coloredBlur"
          />
          <feMerge>
            <feMergeNode in="coloredBlur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <!-- Existing regions -->
      <g
        v-for="(region, index) in localRegions"
        :key="region.id"
      >
        <rect
          :x="toDisplayCoords(region.x, region.y).x"
          :y="toDisplayCoords(region.x, region.y).y"
          :width="toDisplaySize(region.width, region.height).width"
          :height="toDisplaySize(region.width, region.height).height"
          :fill="getColor(index)"
          fill-opacity="0.15"
          :stroke="getColor(index)"
          stroke-width="2"
          filter="url(#regionGlow)"
        />
        <text
          :x="toDisplayCoords(region.x, region.y).x + 6"
          :y="toDisplayCoords(region.x, region.y).y + 16"
          :fill="getColor(index)"
          font-size="12"
          font-family="JetBrains Mono, monospace"
          font-weight="500"
        >
          {{ region.label }}
        </text>
      </g>

      <!-- Drawing rectangle -->
      <rect
        v-if="drawingRect"
        :x="drawingRect.x"
        :y="drawingRect.y"
        :width="drawingRect.width"
        :height="drawingRect.height"
        fill="rgba(0, 217, 255, 0.2)"
        stroke="#00d9ff"
        stroke-width="2"
        stroke-dasharray="6 3"
      />
    </svg>
  </div>
</template>
