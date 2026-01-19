<script setup>
import { ref, computed, onMounted, watch } from 'vue'

const props = defineProps({
  points: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:points'])

const container = ref(null)
const localPoints = ref([])
const draggingIndex = ref(null)
const hoverIndex = ref(null)
const imgRect = ref(null)

const pointLabels = ['TL', 'TR', 'BR', 'BL']
const pointColors = ['#00d9ff', '#00ff9d', '#ff6b6b', '#ffb347']

const isComplete = computed(() => localPoints.value.length === 4)

function getImageElement() {
  if (!container.value) return null
  const streamViewer = container.value.previousElementSibling
  if (!streamViewer) return null
  return streamViewer.querySelector('img')
}

function updateImgRect() {
  const img = getImageElement()
  if (img && img.complete && img.naturalWidth > 0) {
    const rect = img.getBoundingClientRect()
    const containerRect = container.value.getBoundingClientRect()
    imgRect.value = {
      left: rect.left - containerRect.left,
      top: rect.top - containerRect.top,
      width: rect.width,
      height: rect.height,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight
    }
  }
}

function getMousePos(e) {
  if (!container.value) return { x: 0, y: 0 }
  
  updateImgRect()
  
  const containerRect = container.value.getBoundingClientRect()
  const mouseX = e.clientX - containerRect.left
  const mouseY = e.clientY - containerRect.top
  
  if (imgRect.value) {
    const relX = mouseX - imgRect.value.left
    const relY = mouseY - imgRect.value.top
    
    const scaleX = imgRect.value.naturalWidth / imgRect.value.width
    const scaleY = imgRect.value.naturalHeight / imgRect.value.height
    
    return {
      x: Math.round(relX * scaleX),
      y: Math.round(relY * scaleY)
    }
  }
  
  return { x: Math.round(mouseX), y: Math.round(mouseY) }
}

function toDisplayCoords(x, y) {
  if (!imgRect.value) return { x, y }
  
  const scaleX = imgRect.value.width / imgRect.value.naturalWidth
  const scaleY = imgRect.value.height / imgRect.value.naturalHeight
  
  return {
    x: x * scaleX + imgRect.value.left,
    y: y * scaleY + imgRect.value.top
  }
}

function findNearestPoint(pos, threshold = 30) {
  let nearest = -1
  let minDist = threshold
  
  for (let i = 0; i < localPoints.value.length; i++) {
    const p = localPoints.value[i]
    const dist = Math.sqrt((p[0] - pos.x) ** 2 + (p[1] - pos.y) ** 2)
    if (dist < minDist) {
      minDist = dist
      nearest = i
    }
  }
  
  return nearest
}

function handleClick(e) {
  if (draggingIndex.value !== null) return
  
  const pos = getMousePos(e)
  
  if (localPoints.value.length < 4) {
    localPoints.value.push([pos.x, pos.y])
    if (localPoints.value.length === 4) {
      emit('update:points', [...localPoints.value])
    }
  }
}

function handleMouseDown(e) {
  const pos = getMousePos(e)
  const nearest = findNearestPoint(pos)
  
  if (nearest >= 0) {
    draggingIndex.value = nearest
    e.preventDefault()
  }
}

function handleMouseMove(e) {
  const pos = getMousePos(e)
  
  if (draggingIndex.value !== null) {
    localPoints.value[draggingIndex.value] = [pos.x, pos.y]
  } else {
    hoverIndex.value = findNearestPoint(pos)
  }
}

function handleMouseUp() {
  if (draggingIndex.value !== null && localPoints.value.length === 4) {
    emit('update:points', [...localPoints.value])
  }
  draggingIndex.value = null
}

function handleMouseLeave() {
  hoverIndex.value = null
  if (draggingIndex.value !== null && localPoints.value.length === 4) {
    emit('update:points', [...localPoints.value])
  }
  draggingIndex.value = null
}

watch(() => props.points, (newPoints) => {
  if (!draggingIndex.value) {
    localPoints.value = newPoints.map(p => [...p])
  }
}, { immediate: true, deep: true })

onMounted(() => {
  const checkImg = setInterval(() => {
    updateImgRect()
    if (imgRect.value) {
      clearInterval(checkImg)
    }
  }, 100)
  
  setTimeout(() => clearInterval(checkImg), 5000)
  
  window.addEventListener('resize', updateImgRect)
})
</script>

<template>
  <div 
    ref="container"
    class="absolute inset-0 cursor-crosshair"
    @click="handleClick"
    @mousedown="handleMouseDown"
    @mousemove="handleMouseMove"
    @mouseup="handleMouseUp"
    @mouseleave="handleMouseLeave"
  >
    <svg class="w-full h-full pointer-events-none">
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
          <feMerge>
            <feMergeNode in="coloredBlur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>

      <polygon
        v-if="localPoints.length >= 3 && imgRect"
        :points="localPoints.map(p => {
          const d = toDisplayCoords(p[0], p[1])
          return `${d.x},${d.y}`
        }).join(' ')"
        fill="rgba(0, 217, 255, 0.1)"
        stroke="rgba(0, 217, 255, 0.5)"
        stroke-width="2"
        stroke-dasharray="8 4"
      />

      <template v-for="(point, i) in localPoints" :key="'line-' + i">
        <line
          v-if="(i < localPoints.length - 1 || localPoints.length === 4) && imgRect"
          :x1="toDisplayCoords(point[0], point[1]).x"
          :y1="toDisplayCoords(point[0], point[1]).y"
          :x2="toDisplayCoords(localPoints[(i + 1) % localPoints.length][0], localPoints[(i + 1) % localPoints.length][1]).x"
          :y2="toDisplayCoords(localPoints[(i + 1) % localPoints.length][0], localPoints[(i + 1) % localPoints.length][1]).y"
          stroke="rgba(0, 217, 255, 0.6)"
          stroke-width="2"
          filter="url(#glow)"
        />
      </template>

      <g
        v-for="(point, i) in localPoints"
        :key="'point-' + i"
      >
        <circle
          v-if="imgRect"
          :cx="toDisplayCoords(point[0], point[1]).x"
          :cy="toDisplayCoords(point[0], point[1]).y"
          :r="draggingIndex === i || hoverIndex === i ? 14 : 10"
          :fill="pointColors[i]"
          fill-opacity="0.3"
          :stroke="pointColors[i]"
          stroke-width="2"
          filter="url(#glow)"
          class="transition-all duration-150"
        />
        <circle
          v-if="imgRect"
          :cx="toDisplayCoords(point[0], point[1]).x"
          :cy="toDisplayCoords(point[0], point[1]).y"
          r="4"
          :fill="pointColors[i]"
        />
        <text
          v-if="imgRect"
          :x="toDisplayCoords(point[0], point[1]).x"
          :y="toDisplayCoords(point[0], point[1]).y - 18"
          text-anchor="middle"
          :fill="pointColors[i]"
          font-size="12"
          font-family="JetBrains Mono, monospace"
          font-weight="600"
        >
          {{ pointLabels[i] }}
        </text>
      </g>
    </svg>

    <div 
      v-if="!isComplete"
      class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-midnight-900/90 backdrop-blur px-4 py-2 rounded-lg border border-midnight-700"
    >
      <span class="text-sm text-midnight-300">
        Click to place point {{ localPoints.length + 1 }} of 4
        <span class="text-midnight-500 ml-2">({{ pointLabels[localPoints.length] }})</span>
      </span>
    </div>

    <div 
      v-else
      class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-electric-500/20 backdrop-blur px-4 py-2 rounded-lg border border-electric-500/30"
    >
      <span class="text-sm text-electric-400">
        Drag points to adjust • Clear in settings panel
      </span>
    </div>
  </div>
</template>
