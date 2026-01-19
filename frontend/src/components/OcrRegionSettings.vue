<script setup>
import { ref, computed } from 'vue'
import { detectGlyphs, addGlyph, updateGlyph, deleteGlyph, clearGlyphs, combineGlyphs } from '../api'

const props = defineProps({
  session: Object,
  ocrResults: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['delete-region', 'clear-regions', 'rename-region', 'update-backend', 'glyphs-updated'])

const colors = ['#00d9ff', '#00ff9d', '#ff6b6b', '#ffb347', '#c084fc', '#f472b6']
const editingId = ref(null)
const editingName = ref('')

// Glyph training state
const detectedGlyphs = ref([])
const glyphLabels = ref({})
const isDetecting = ref(false)
const selectedRegionForGlyphs = ref(null)
const mergeVertical = ref(true)  // Auto-merge vertical glyphs like ':'
const selectedGlyphIndices = ref(new Set())  // For manual combining
const combineLabel = ref('')  // Label for combined glyph

function getColor(index) {
  return colors[index % colors.length]
}

function startEditing(region) {
  editingId.value = region.id
  editingName.value = region.label
}

function saveEdit(regionId) {
  if (editingName.value.trim()) {
    emit('rename-region', regionId, editingName.value.trim())
  }
  editingId.value = null
  editingName.value = ''
}

function cancelEdit() {
  editingId.value = null
  editingName.value = ''
}

function getRegionText(regionName) {
  const detections = props.ocrResults[regionName] || []
  return detections.map(d => d.text).join(' ')
}

function getRegionConfidence(regionName) {
  const detections = props.ocrResults[regionName] || []
  if (detections.length === 0) return null
  const avg = detections.reduce((sum, d) => sum + d.confidence, 0) / detections.length
  return Math.round(avg * 100)
}

function hasDetections(regionName) {
  const detections = props.ocrResults[regionName] || []
  return detections.length > 0
}

const allRegionNames = computed(() => {
  const fromResults = Object.keys(props.ocrResults)
  const fromRegions = (props.session?.ocr_regions || []).map(r => r.label)
  const all = new Set([...fromResults, ...fromRegions])
  return Array.from(all).filter(n => n !== '_full')
})

// Glyph training functions
async function handleDetectGlyphs() {
  if (!props.session) return
  isDetecting.value = true
  selectedGlyphIndices.value = new Set()
  combineLabel.value = ''
  try {
    const result = await detectGlyphs(props.session.id, selectedRegionForGlyphs.value, mergeVertical.value)
    detectedGlyphs.value = result.glyphs
    // Pre-fill labels with existing glyph matches
    glyphLabels.value = {}
    for (const glyph of result.glyphs) {
      glyphLabels.value[glyph.index] = ''
    }
  } catch (e) {
    console.error('Failed to detect glyphs:', e)
  }
  isDetecting.value = false
}

function toggleGlyphSelection(index) {
  if (selectedGlyphIndices.value.has(index)) {
    selectedGlyphIndices.value.delete(index)
  } else {
    selectedGlyphIndices.value.add(index)
  }
  // Trigger reactivity
  selectedGlyphIndices.value = new Set(selectedGlyphIndices.value)
}

function isGlyphSelected(index) {
  return selectedGlyphIndices.value.has(index)
}

const selectedCount = computed(() => selectedGlyphIndices.value.size)

async function handleCombineSelected() {
  if (!props.session || selectedGlyphIndices.value.size < 2 || !combineLabel.value) return
  
  try {
    const indices = Array.from(selectedGlyphIndices.value).sort((a, b) => a - b)
    const combined = await combineGlyphs(props.session.id, indices, selectedRegionForGlyphs.value)
    
    // Save the combined glyph
    await addGlyph(props.session.id, combineLabel.value, combined.template, combined.width, combined.height)
    emit('glyphs-updated')
    
    // Remove combined glyphs from detected list
    detectedGlyphs.value = detectedGlyphs.value.filter(g => !selectedGlyphIndices.value.has(g.index))
    selectedGlyphIndices.value = new Set()
    combineLabel.value = ''
  } catch (e) {
    console.error('Failed to combine glyphs:', e)
  }
}

function clearSelection() {
  selectedGlyphIndices.value = new Set()
  combineLabel.value = ''
}

async function handleSaveGlyph(glyph) {
  const char = glyphLabels.value[glyph.index]
  if (!char || !props.session) return
  
  try {
    await addGlyph(props.session.id, char, glyph.template, glyph.width, glyph.height)
    emit('glyphs-updated')
    // Remove from detected list
    detectedGlyphs.value = detectedGlyphs.value.filter(g => g.index !== glyph.index)
  } catch (e) {
    console.error('Failed to save glyph:', e)
  }
}

async function handleDeleteGlyph(glyphId) {
  if (!props.session) return
  try {
    await deleteGlyph(props.session.id, glyphId)
    emit('glyphs-updated')
  } catch (e) {
    console.error('Failed to delete glyph:', e)
  }
}

async function handleClearGlyphs() {
  if (!props.session) return
  try {
    await clearGlyphs(props.session.id)
    emit('glyphs-updated')
  } catch (e) {
    console.error('Failed to clear glyphs:', e)
  }
}

function templateToDataUrl(template) {
  // Convert template (2D array) to a canvas data URL for display
  const canvas = document.createElement('canvas')
  canvas.width = template[0]?.length || 32
  canvas.height = template.length || 48
  const ctx = canvas.getContext('2d')
  const imageData = ctx.createImageData(canvas.width, canvas.height)
  
  for (let y = 0; y < template.length; y++) {
    for (let x = 0; x < template[y].length; x++) {
      const i = (y * canvas.width + x) * 4
      const val = template[y][x]
      imageData.data[i] = val
      imageData.data[i + 1] = val
      imageData.data[i + 2] = val
      imageData.data[i + 3] = 255
    }
  }
  
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL()
}
</script>

<template>
  <div class="p-5 space-y-6">
    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">OCR Regions</h3>
        <button 
          v-if="session?.ocr_regions?.length"
          @click="$emit('clear-regions')"
          class="text-xs text-midnight-600 hover:text-ember-400 transition-colors"
        >
          Clear All
        </button>
      </div>

      <div v-if="!session?.ocr_regions?.length" class="text-sm text-midnight-600 text-center py-4">
        No regions defined. Draw rectangles on the video to create OCR regions.
      </div>

      <div v-else class="space-y-3">
        <div 
          v-for="(region, index) in session.ocr_regions" 
          :key="region.id"
          class="bg-midnight-800/50 rounded-lg p-3 border border-midnight-700"
        >
          <!-- Header row -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 flex-1 min-w-0">
              <div 
                class="w-3 h-3 rounded flex-shrink-0"
                :style="{ backgroundColor: getColor(index) }"
              />
              
              <template v-if="editingId === region.id">
                <input
                  v-model="editingName"
                  @keyup.enter="saveEdit(region.id)"
                  @keyup.escape="cancelEdit"
                  @blur="saveEdit(region.id)"
                  class="flex-1 bg-midnight-900 border border-midnight-600 rounded px-2 py-1 text-sm text-midnight-100 focus:outline-none focus:border-electric-500"
                  autofocus
                />
              </template>
              <template v-else>
                <span 
                  class="text-sm text-midnight-300 truncate cursor-pointer hover:text-electric-400"
                  @dblclick="startEditing(region)"
                  :title="'Double-click to rename'"
                >
                  {{ region.label }}
                </span>
              </template>
            </div>
            <button
              @click="$emit('delete-region', region.id)"
              class="p-1 text-midnight-600 hover:text-ember-400 transition-colors flex-shrink-0 ml-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

          <!-- Position info -->
          <div class="mt-2 text-xs text-midnight-500 font-mono">
            {{ region.x }}, {{ region.y }} — {{ region.width }}×{{ region.height }}
          </div>

          <!-- Backend selector -->
          <div class="mt-2 flex items-center gap-2">
            <span class="text-xs text-midnight-500">Backend:</span>
            <select
              :value="region.ocr_backend || 'tesseract'"
              @change="(e) => $emit('update-backend', region.id, e.target.value)"
              class="bg-midnight-900 border border-midnight-700 rounded px-2 py-1 text-xs text-midnight-300 focus:outline-none focus:border-electric-500"
            >
              <option value="tesseract">Tesseract</option>
              <option value="easyocr">EasyOCR</option>
              <option value="glyphs">Glyphs (Custom)</option>
            </select>
          </div>

          <!-- OCR Result -->
          <div class="mt-3 pt-2 border-t border-midnight-700">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs text-midnight-500">OCR Result</span>
              <span v-if="getRegionConfidence(region.label)" class="text-xs text-midnight-600">
                {{ getRegionConfidence(region.label) }}%
              </span>
            </div>
            <div 
              class="font-mono text-sm p-2 rounded bg-midnight-900/50"
              :class="hasDetections(region.label) ? 'text-electric-400' : 'text-midnight-600 italic'"
            >
              {{ getRegionText(region.label) || 'No text detected' }}
            </div>
          </div>
        </div>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <!-- Glyph Training Section -->
    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">Glyph Training</h3>
        <button 
          v-if="session?.glyphs?.length"
          @click="handleClearGlyphs"
          class="text-xs text-midnight-600 hover:text-ember-400 transition-colors"
        >
          Clear All
        </button>
      </div>

      <p class="text-xs text-midnight-600 mb-3">
        Train custom glyphs for seven-segment displays. Select a region and detect the characters.
      </p>

      <!-- Region selector for detection -->
      <div class="flex gap-2 mb-2">
        <select
          v-model="selectedRegionForGlyphs"
          class="flex-1 bg-midnight-900 border border-midnight-700 rounded px-2 py-2 text-xs text-midnight-300 focus:outline-none focus:border-electric-500"
        >
          <option :value="null">Full processed frame</option>
          <option v-for="region in session?.ocr_regions" :key="region.id" :value="region.id">
            {{ region.label }}
          </option>
        </select>
        <button
          @click="handleDetectGlyphs"
          :disabled="isDetecting"
          class="px-3 py-2 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-xs font-medium rounded transition-colors"
        >
          {{ isDetecting ? 'Detecting...' : 'Detect' }}
        </button>
      </div>

      <!-- Merge vertical option -->
      <label class="flex items-center gap-2 mb-3 text-xs text-midnight-400 cursor-pointer">
        <input
          type="checkbox"
          v-model="mergeVertical"
          class="w-3.5 h-3.5 rounded border-midnight-600 bg-midnight-900 text-electric-500 focus:ring-electric-500 focus:ring-offset-0"
        />
        <span>Auto-merge vertical (for ":" etc.)</span>
      </label>

      <!-- Detected glyphs for labeling -->
      <div v-if="detectedGlyphs.length" class="mb-4">
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs text-midnight-500">Detected Glyphs ({{ detectedGlyphs.length }})</div>
          <div v-if="selectedCount > 0" class="text-xs text-electric-400">
            {{ selectedCount }} selected
          </div>
        </div>

        <!-- Combine UI when multiple selected -->
        <div v-if="selectedCount >= 2" class="bg-electric-500/10 border border-electric-500/30 rounded-lg p-3 mb-3">
          <div class="text-xs text-electric-400 mb-2">Combine {{ selectedCount }} glyphs into one:</div>
          <div class="flex gap-2">
            <input
              v-model="combineLabel"
              maxlength="3"
              placeholder="Label (e.g. :)"
              class="flex-1 bg-midnight-900 border border-midnight-700 rounded px-2 py-1.5 text-xs text-midnight-200 focus:outline-none focus:border-electric-500"
              @keyup.enter="handleCombineSelected"
            />
            <button
              @click="handleCombineSelected"
              :disabled="!combineLabel"
              class="px-3 py-1.5 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-xs font-medium rounded transition-colors"
            >
              Combine
            </button>
            <button
              @click="clearSelection"
              class="px-2 py-1.5 bg-midnight-700 hover:bg-midnight-600 text-midnight-300 text-xs rounded transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>

        <p class="text-xs text-midnight-600 mb-2">
          Click to select multiple glyphs to combine (e.g. for ":")
        </p>

        <div class="grid grid-cols-4 gap-2">
          <div 
            v-for="glyph in detectedGlyphs" 
            :key="glyph.index"
            @click="toggleGlyphSelection(glyph.index)"
            class="rounded p-2 text-center cursor-pointer transition-all"
            :class="isGlyphSelected(glyph.index) 
              ? 'bg-electric-500/20 border-2 border-electric-500' 
              : 'bg-midnight-800 border-2 border-transparent hover:border-midnight-600'"
          >
            <img 
              :src="templateToDataUrl(glyph.template)" 
              class="w-8 h-12 mx-auto mb-1 object-contain bg-white rounded"
              style="image-rendering: pixelated;"
            />
            <div v-if="glyph.merged_count > 1" class="text-[10px] text-midnight-500 mb-1">
              (merged: {{ glyph.merged_count }})
            </div>
            <input
              v-model="glyphLabels[glyph.index]"
              maxlength="2"
              placeholder="?"
              @click.stop
              class="w-full bg-midnight-900 border border-midnight-700 rounded px-1 py-0.5 text-xs text-center text-midnight-200 focus:outline-none focus:border-electric-500"
              @keyup.enter="handleSaveGlyph(glyph)"
            />
            <button
              @click.stop="handleSaveGlyph(glyph)"
              :disabled="!glyphLabels[glyph.index]"
              class="w-full mt-1 px-2 py-0.5 bg-electric-500/20 hover:bg-electric-500/30 disabled:bg-midnight-700/50 text-electric-400 disabled:text-midnight-600 text-xs rounded"
            >
              Save
            </button>
          </div>
        </div>
      </div>

      <!-- Saved glyphs -->
      <div v-if="session?.glyphs?.length">
        <div class="text-xs text-midnight-500 mb-2">Trained Glyphs ({{ session.glyphs.length }})</div>
        <div class="flex flex-wrap gap-2">
          <div 
            v-for="glyph in session.glyphs" 
            :key="glyph.id"
            class="bg-midnight-800 rounded p-2 text-center relative group"
          >
            <img 
              :src="templateToDataUrl(glyph.template)" 
              class="w-6 h-9 mx-auto mb-1 object-contain bg-white rounded"
              style="image-rendering: pixelated;"
            />
            <div class="text-xs text-electric-400 font-mono">{{ glyph.char }}</div>
            <button
              @click="handleDeleteGlyph(glyph.id)"
              class="absolute -top-1 -right-1 w-4 h-4 bg-ember-500 text-white rounded-full text-xs opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
            >
              ×
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="!detectedGlyphs.length" class="text-sm text-midnight-600 text-center py-4">
        No glyphs trained yet. Click "Detect" to find characters.
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-4">Info</h3>
      
      <div class="space-y-2 text-sm">
        <div class="flex items-center justify-between">
          <span class="text-midnight-400">Output Resolution</span>
          <span class="text-midnight-300 font-mono">
            {{ session?.perspective_output_size?.[0] || 800 }} × {{ session?.perspective_output_size?.[1] || 600 }}
          </span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-midnight-400">Color Filters</span>
          <span class="text-midnight-300">
            {{ session?.color_filters?.length || 0 }} active
          </span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-midnight-400">Trained Glyphs</span>
          <span class="text-midnight-300">
            {{ session?.glyphs?.length || 0 }}
          </span>
        </div>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-3">API Endpoints</h3>
      <div class="space-y-2 text-xs">
        <div class="bg-midnight-800/50 rounded p-2 font-mono text-midnight-400">
          GET /ocr/{{ session?.id }}
        </div>
        <p class="text-midnight-600">Returns all regions with OCR results as JSON</p>
        
        <div class="bg-midnight-800/50 rounded p-2 font-mono text-midnight-400">
          GET /ocr/{{ session?.id }}/{'{region_name}'}
        </div>
        <p class="text-midnight-600">Returns plain text result for a specific region</p>
      </div>
    </section>
  </div>
</template>
