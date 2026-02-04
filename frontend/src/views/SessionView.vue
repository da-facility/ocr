<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { 
  getSession, updatePerspective, addColorFilter, updateColorFilter, 
  deleteColorFilter, clearColorFilters, updateMorphology, pickColor,
  addOcrRegion, updateOcrRegion, deleteOcrRegion, clearOcrRegions,
  getStreamUrl, createOcrWebSocket 
} from '../api'
import StreamViewer from '../components/StreamViewer.vue'
import PerspectiveCanvas from '../components/PerspectiveCanvas.vue'
import PerspectiveSettings from '../components/PerspectiveSettings.vue'
import ColorSettings from '../components/ColorSettings.vue'
import OcrRegionCanvas from '../components/OcrRegionCanvas.vue'
import OcrRegionSettings from '../components/OcrRegionSettings.vue'

const route = useRoute()
const router = useRouter()
const sessionId = computed(() => route.params.id)

const session = ref(null)
const activeTab = ref('perspective')
const ocrResults = ref({})
const loading = ref(true)
const error = ref(null)
const colorPickerMode = ref(false)
const colorsLayout = ref('vertical')

let ws = null

const tabs = [
  { id: 'perspective', label: 'Set Perspective' },
  { id: 'colors', label: 'Set Colors' },
  { id: 'ocr', label: 'Set OCR Regions' }
]

const perspectiveStreamUrl = computed(() => {
  if (!session.value) return null
  return getStreamUrl(sessionId.value, 'perspective')
})

const processedStreamUrl = computed(() => {
  if (!session.value) return null
  return getStreamUrl(sessionId.value, 'processed')
})

const originalStreamUrl = computed(() => {
  if (!session.value) return null
  return getStreamUrl(sessionId.value, 'original')
})

const perspectivePoints = computed(() => {
  return session.value?.perspective_points || []
})

const perspectiveSize = computed(() => {
  return session.value?.perspective_output_size || [800, 600]
})

async function loadSession() {
  loading.value = true
  error.value = null
  try {
    session.value = await getSession(sessionId.value)
  } catch (err) {
    console.error(err)
    error.value = 'Session not found'
  } finally {
    loading.value = false
  }
}

async function handlePerspectiveChange(points) {
  try {
    const result = await updatePerspective(sessionId.value, points.length === 4 ? points : null)
    if (session.value) {
      session.value.perspective_points = result.perspective_points
    }
  } catch (e) {
    console.error('Failed to update perspective:', e)
  }
}

async function handleClearPerspective() {
  try {
    await updatePerspective(sessionId.value, null)
    if (session.value) {
      session.value.perspective_points = null
    }
  } catch (e) {
    console.error('Failed to clear perspective:', e)
  }
}

async function handleColorPick(x, y) {
  if (!colorPickerMode.value) return
  try {
    const result = await pickColor(sessionId.value, x, y)
    const filter = await addColorFilter(sessionId.value, result.bgr, [30, 30, 30])
    if (session.value) {
      session.value.color_filters.push(filter)
    }
  } catch (e) {
    console.error('Failed to pick color:', e)
  }
  colorPickerMode.value = false
}

async function handleAddColorFilter(bgr, tolerance) {
  try {
    const filter = await addColorFilter(sessionId.value, bgr, tolerance)
    if (session.value) {
      session.value.color_filters.push(filter)
    }
  } catch (e) {
    console.error('Failed to add color filter:', e)
  }
}

async function handleUpdateColorFilter(filterId, tolerance) {
  try {
    await updateColorFilter(sessionId.value, filterId, tolerance)
    if (session.value) {
      const filter = session.value.color_filters.find(f => f.id === filterId)
      if (filter) {
        filter.tolerance = tolerance
      }
    }
  } catch (e) {
    console.error('Failed to update color filter:', e)
  }
}

async function handleDeleteColorFilter(filterId) {
  try {
    await deleteColorFilter(sessionId.value, filterId)
    if (session.value) {
      session.value.color_filters = session.value.color_filters.filter(f => f.id !== filterId)
    }
  } catch (e) {
    console.error('Failed to delete color filter:', e)
  }
}

async function handleClearColorFilters() {
  try {
    await clearColorFilters(sessionId.value)
    if (session.value) {
      session.value.color_filters = []
    }
  } catch (e) {
    console.error('Failed to clear color filters:', e)
  }
}

async function handleMorphologyChange(erosion, dilation) {
  try {
    await updateMorphology(sessionId.value, erosion, dilation)
    if (session.value) {
      session.value.erosion_kernel = erosion
      session.value.dilation_kernel = dilation
    }
  } catch (e) {
    console.error('Failed to update morphology:', e)
  }
}

async function handleAddOcrRegion(x, y, width, height) {
  try {
    const region = await addOcrRegion(sessionId.value, x, y, width, height)
    if (session.value) {
      session.value.ocr_regions.push(region)
    }
  } catch (e) {
    console.error('Failed to add OCR region:', e)
  }
}

async function handleUpdateOcrRegion(regionId, data) {
  try {
    await updateOcrRegion(sessionId.value, regionId, data)
    if (session.value) {
      const region = session.value.ocr_regions.find(r => r.id === regionId)
      if (region) {
        Object.assign(region, data)
      }
    }
  } catch (e) {
    console.error('Failed to update OCR region:', e)
  }
}

async function handleDeleteOcrRegion(regionId) {
  try {
    await deleteOcrRegion(sessionId.value, regionId)
    if (session.value) {
      session.value.ocr_regions = session.value.ocr_regions.filter(r => r.id !== regionId)
    }
  } catch (e) {
    console.error('Failed to delete OCR region:', e)
  }
}

async function handleClearOcrRegions() {
  try {
    await clearOcrRegions(sessionId.value)
    if (session.value) {
      session.value.ocr_regions = []
    }
  } catch (e) {
    console.error('Failed to clear OCR regions:', e)
  }
}

async function handleRenameRegion(regionId, newLabel) {
  try {
    await updateOcrRegion(sessionId.value, regionId, { label: newLabel })
    if (session.value) {
      const region = session.value.ocr_regions.find(r => r.id === regionId)
      if (region) {
        region.label = newLabel
      }
    }
  } catch (e) {
    console.error('Failed to rename region:', e)
  }
}

function toggleColorsLayout() {
  colorsLayout.value = colorsLayout.value === 'vertical' ? 'horizontal' : 'vertical'
}

function connectWebSocket() {
  if (ws) {
    ws.close()
  }
  ws = createOcrWebSocket(sessionId.value, (results) => {
    ocrResults.value = results
  })
}

function goHome() {
  router.push('/')
}

onMounted(() => {
  loadSession()
  connectWebSocket()
})

onUnmounted(() => {
  if (ws) {
    ws.close()
  }
})

watch(sessionId, () => {
  loadSession()
  connectWebSocket()
})
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden">
    <header class="border-b border-midnight-800 px-6 py-4 flex items-center justify-between bg-midnight-900/50 backdrop-blur flex-shrink-0">
      <div class="flex items-center gap-4">
        <button 
          class="p-2 text-midnight-500 hover:text-electric-400 hover:bg-midnight-800 rounded-lg transition-colors"
          @click="goHome"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-5 w-5"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z"
              clip-rule="evenodd"
            />
          </svg>
        </button>
        <div>
          <h1 class="text-lg font-medium">
            <span class="text-midnight-500">Session</span>
            <span class="text-electric-400 ml-2 font-mono">{{ sessionId }}</span>
          </h1>
        </div>
      </div>
      <div
        v-if="session"
        class="text-sm text-midnight-500"
      >
        {{ session.camera_name || `Camera ${session.camera_index}` }}
      </div>
    </header>

    <div
      v-if="loading"
      class="flex-1 flex items-center justify-center"
    >
      <div class="text-midnight-500">
        Loading session...
      </div>
    </div>

    <div
      v-else-if="error"
      class="flex-1 flex items-center justify-center"
    >
      <div class="text-center">
        <div class="text-ember-400 mb-4">
          {{ error }}
        </div>
        <button
          class="text-electric-400 hover:underline"
          @click="goHome"
        >
          Go back home
        </button>
      </div>
    </div>

    <div
      v-else
      class="flex-1 flex overflow-hidden"
    >
      <main class="flex-1 flex flex-col min-w-0 overflow-hidden">
        <nav class="flex border-b border-midnight-800 bg-midnight-900/30 flex-shrink-0">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            :class="[
              'px-6 py-3 text-sm font-medium transition-colors relative',
              activeTab === tab.id 
                ? 'text-electric-400' 
                : 'text-midnight-500 hover:text-midnight-300'
            ]"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
            <div 
              v-if="activeTab === tab.id"
              class="absolute bottom-0 left-0 right-0 h-0.5 bg-electric-400"
            />
          </button>
        </nav>

        <!-- Tab 1: Set Perspective - single original stream -->
        <div
          v-if="activeTab === 'perspective'"
          class="flex-1 relative bg-midnight-950 overflow-hidden min-h-0"
        >
          <StreamViewer 
            :src="originalStreamUrl" 
            class="w-full h-full"
          />
          <PerspectiveCanvas
            :points="perspectivePoints"
            class="absolute inset-0"
            @update:points="handlePerspectiveChange"
          />
        </div>

        <!-- Tab 2: Set Colors - perspective and processed (stacked or side by side) -->
        <div 
          v-if="activeTab === 'colors'" 
          class="flex-1 bg-midnight-950 overflow-hidden"
          :class="colorsLayout === 'vertical' ? 'flex flex-col' : 'flex flex-row'"
        >
          <div 
            class="flex-1 relative overflow-hidden"
            :class="[
              colorsLayout === 'vertical' ? 'min-h-0 border-b border-midnight-800' : 'min-w-0 border-r border-midnight-800'
            ]"
          >
            <StreamViewer 
              :src="perspectiveStreamUrl" 
              class="w-full h-full"
            />
            <div 
              v-if="colorPickerMode"
              class="absolute inset-0 cursor-crosshair"
              @click="(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                const img = e.currentTarget.previousElementSibling?.querySelector('img')
                if (img) {
                  const imgRect = img.getBoundingClientRect()
                  const x = Math.round((e.clientX - imgRect.left) * (perspectiveSize[0] / imgRect.width))
                  const y = Math.round((e.clientY - imgRect.top) * (perspectiveSize[1] / imgRect.height))
                  handleColorPick(x, y)
                }
              }"
            >
              <div class="absolute inset-0 bg-electric-400/10 flex items-center justify-center">
                <div class="bg-midnight-900/90 backdrop-blur px-4 py-2 rounded-lg border border-electric-500/30">
                  <span class="text-sm text-electric-400">Click to pick a color</span>
                </div>
              </div>
            </div>
            <div class="absolute top-2 left-2 bg-midnight-900/80 backdrop-blur px-2 py-1 rounded text-xs text-midnight-400">
              Perspective Corrected
            </div>
          </div>
          <div 
            class="flex-1 relative overflow-hidden"
            :class="colorsLayout === 'vertical' ? 'min-h-0' : 'min-w-0'"
          >
            <StreamViewer 
              :src="processedStreamUrl" 
              class="w-full h-full"
            />
            <div class="absolute top-2 left-2 bg-midnight-900/80 backdrop-blur px-2 py-1 rounded text-xs text-midnight-400">
              Processed
            </div>
          </div>
        </div>

        <!-- Tab 3: Set OCR Regions - processed stream with region overlay -->
        <div
          v-if="activeTab === 'ocr'"
          class="flex-1 relative bg-midnight-950"
        >
          <StreamViewer 
            :src="processedStreamUrl" 
            class="w-full h-full"
          />
          <OcrRegionCanvas
            :regions="session?.ocr_regions || []"
            :frame-size="perspectiveSize"
            class="absolute inset-0"
            @add-region="handleAddOcrRegion"
            @update-region="handleUpdateOcrRegion"
          />
        </div>
      </main>

      <aside class="w-80 border-l border-midnight-800 bg-midnight-900/30 overflow-y-auto flex-shrink-0">
        <!-- Perspective Settings (Tab 1) -->
        <PerspectiveSettings
          v-if="activeTab === 'perspective' && session"
          :session="session"
          @clear-perspective="handleClearPerspective"
        />

        <!-- Color Settings (Tab 2) -->
        <ColorSettings
          v-if="activeTab === 'colors' && session"
          :session="session"
          :color-picker-mode="colorPickerMode"
          :layout="colorsLayout"
          @toggle-picker="colorPickerMode = !colorPickerMode"
          @toggle-layout="toggleColorsLayout"
          @add-filter="handleAddColorFilter"
          @update-filter="handleUpdateColorFilter"
          @delete-filter="handleDeleteColorFilter"
          @clear-filters="handleClearColorFilters"
          @update-morphology="handleMorphologyChange"
        />

        <!-- OCR Region Settings (Tab 3) -->
        <OcrRegionSettings
          v-if="activeTab === 'ocr' && session"
          :session="session"
          :ocr-results="ocrResults"
          @delete-region="handleDeleteOcrRegion"
          @clear-regions="handleClearOcrRegions"
          @rename-region="handleRenameRegion"
          @glyphs-updated="loadSession"
          @region-updated="loadSession"
        />
      </aside>
    </div>
  </div>
</template>
