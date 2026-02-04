<script setup>
import { ref, computed, onMounted } from 'vue'
import { 
  detectGlyphs, addGlyph, updateGlyph, deleteGlyph, clearGlyphs, combineGlyphs,
  listGlyphSets, exportGlyphs, importGlyphs, deleteGlyphSet,
  updateOcrRegion, resetRegionValidator
} from '../api'

const props = defineProps({
  session: {
    type: Object,
    default: null
  },
  ocrResults: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['delete-region', 'clear-regions', 'rename-region', 'glyphs-updated', 'region-updated'])

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

// Glyph storage state
const glyphSets = ref([])
const showExportDialog = ref(false)
const showImportDialog = ref(false)
const exportName = ref('')
const selectedImportSet = ref(null)
const importReplace = ref(false)

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

function getRegionConfidence(regionName) {
  const result = props.ocrResults[regionName]
  if (!result || !Array.isArray(result.detections) || result.detections.length === 0) return null
  const avg = result.detections.reduce((sum, d) => sum + d.confidence, 0) / result.detections.length
  return Math.round(avg * 100)
}

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

async function handleSaveGlyph(glyph, ignored = false) {
  const char = glyphLabels.value[glyph.index]
  if (!char || !props.session) return
  
  try {
    await addGlyph(props.session.id, char, glyph.template, glyph.width, glyph.height, ignored)
    emit('glyphs-updated')
    // Remove from detected list
    detectedGlyphs.value = detectedGlyphs.value.filter(g => g.index !== glyph.index)
  } catch (e) {
    console.error('Failed to save glyph:', e)
  }
}

async function handleIgnoreGlyph(glyph) {
  if (!props.session) return
  
  try {
    // Save as ignored glyph with placeholder character
    await addGlyph(props.session.id, '_', glyph.template, glyph.width, glyph.height, true)
    emit('glyphs-updated')
    // Remove from detected list
    detectedGlyphs.value = detectedGlyphs.value.filter(g => g.index !== glyph.index)
  } catch (e) {
    console.error('Failed to ignore glyph:', e)
  }
}

async function handleToggleIgnored(glyphId, currentIgnored) {
  if (!props.session) return
  try {
    await updateGlyph(props.session.id, glyphId, null, !currentIgnored)
    emit('glyphs-updated')
  } catch (e) {
    console.error('Failed to toggle ignored:', e)
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

// Glyph storage functions
async function loadGlyphSets() {
  try {
    glyphSets.value = await listGlyphSets()
  } catch (e) {
    console.error('Failed to load glyph sets:', e)
  }
}

async function handleExportGlyphs() {
  if (!props.session || !exportName.value.trim()) return
  
  try {
    await exportGlyphs(props.session.id, exportName.value.trim())
    showExportDialog.value = false
    exportName.value = ''
    await loadGlyphSets()
  } catch (e) {
    console.error('Failed to export glyphs:', e)
  }
}

async function handleImportGlyphs() {
  if (!props.session || !selectedImportSet.value) return
  
  try {
    await importGlyphs(props.session.id, selectedImportSet.value, importReplace.value)
    showImportDialog.value = false
    selectedImportSet.value = null
    importReplace.value = false
    emit('glyphs-updated')
  } catch (e) {
    console.error('Failed to import glyphs:', e)
  }
}

async function handleDeleteGlyphSet(setId) {
  try {
    await deleteGlyphSet(setId)
    await loadGlyphSets()
  } catch (e) {
    console.error('Failed to delete glyph set:', e)
  }
}

function openExportDialog() {
  exportName.value = props.session?.camera_name || `Session ${props.session?.id}`
  showExportDialog.value = true
}

function openImportDialog() {
  loadGlyphSets()
  showImportDialog.value = true
}

// Region type functions
async function handleRegionTypeChange(regionId, regionType) {
  if (!props.session) return
  try {
    await updateOcrRegion(props.session.id, regionId, { region_type: regionType })
    emit('region-updated')
  } catch (e) {
    console.error('Failed to update region type:', e)
  }
}

async function handleScoreSubtypeChange(regionId, subtype) {
  if (!props.session) return
  try {
    await updateOcrRegion(props.session.id, regionId, { score_subtype: subtype || '' })
    emit('region-updated')
  } catch (e) {
    console.error('Failed to update score subtype:', e)
  }
}

async function handleTimeFormatChange(regionId, format) {
  if (!props.session) return
  try {
    await updateOcrRegion(props.session.id, regionId, { time_format: format })
    emit('region-updated')
  } catch (e) {
    console.error('Failed to update time format:', e)
  }
}

async function handleResetValidator(regionId) {
  if (!props.session) return
  try {
    await resetRegionValidator(props.session.id, regionId)
  } catch (e) {
    console.error('Failed to reset validator:', e)
  }
}

function getResultText(regionName) {
  const result = props.ocrResults[regionName]
  if (!result) return null
  return result.text || null
}

function getResultTime(regionName) {
  const result = props.ocrResults[regionName]
  if (!result || !result.time) return null
  return result.time
}

onMounted(() => {
  loadGlyphSets()
})

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
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">
          OCR Regions
        </h3>
        <button 
          v-if="session?.ocr_regions?.length"
          class="text-xs text-midnight-600 hover:text-ember-400 transition-colors"
          @click="$emit('clear-regions')"
        >
          Clear All
        </button>
      </div>

      <div
        v-if="!session?.ocr_regions?.length"
        class="text-sm text-midnight-600 text-center py-4"
      >
        No regions defined. Draw rectangles on the video to create OCR regions.
      </div>

      <div
        v-else
        class="space-y-3"
      >
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
                  class="flex-1 bg-midnight-900 border border-midnight-600 rounded px-2 py-1 text-sm text-midnight-100 focus:outline-none focus:border-electric-500"
                  autofocus
                  @keyup.enter="saveEdit(region.id)"
                  @keyup.escape="cancelEdit"
                  @blur="saveEdit(region.id)"
                >
              </template>
              <template v-else>
                <span 
                  class="text-sm text-midnight-300 truncate cursor-pointer hover:text-electric-400"
                  :title="'Double-click to rename'"
                  @dblclick="startEditing(region)"
                >
                  {{ region.label }}
                </span>
              </template>
            </div>
            <button
              class="p-1 text-midnight-600 hover:text-ember-400 transition-colors flex-shrink-0 ml-2"
              @click="$emit('delete-region', region.id)"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                class="h-4 w-4"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fill-rule="evenodd"
                  d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                  clip-rule="evenodd"
                />
              </svg>
            </button>
          </div>

          <!-- Position info -->
          <div class="mt-2 text-xs text-midnight-500 font-mono">
            {{ region.x }}, {{ region.y }} — {{ region.width }}×{{ region.height }}
          </div>

          <!-- Type selector -->
          <div class="mt-2 flex items-center gap-2">
            <span class="text-xs text-midnight-500">Type:</span>
            <select
              :value="region.region_type || 'generic'"
              class="bg-midnight-900 border border-midnight-700 rounded px-2 py-1 text-xs text-midnight-300 focus:outline-none focus:border-electric-500"
              @change="(e) => handleRegionTypeChange(region.id, e.target.value)"
            >
              <option value="generic">
                Generic
              </option>
              <option value="time">
                Time
              </option>
              <option value="score">
                Score
              </option>
            </select>

            <!-- Score subtype selector -->
            <template v-if="region.region_type === 'score'">
              <select
                :value="region.score_subtype || ''"
                class="bg-midnight-900 border border-midnight-700 rounded px-2 py-1 text-xs text-midnight-300 focus:outline-none focus:border-electric-500"
                @change="(e) => handleScoreSubtypeChange(region.id, e.target.value)"
              >
                <option value="">
                  Any
                </option>
                <option value="singles">
                  Singles (+/-1)
                </option>
              </select>
              
              <!-- Reset button for singles mode -->
              <button
                v-if="region.score_subtype === 'singles'"
                class="px-2 py-1 bg-ember-500/20 hover:bg-ember-500/30 text-ember-400 text-xs rounded"
                title="Reset validator state"
                @click="handleResetValidator(region.id)"
              >
                Reset
              </button>
            </template>

            <!-- Time format selector -->
            <template v-if="region.region_type === 'time'">
              <select
                :value="region.time_format || 'm:ss'"
                class="bg-midnight-900 border border-midnight-700 rounded px-2 py-1 text-xs text-midnight-300 focus:outline-none focus:border-electric-500"
                @change="(e) => handleTimeFormatChange(region.id, e.target.value)"
              >
                <option value="m:ss">
                  m:ss
                </option>
                <option value="mm:ss">
                  mm:ss
                </option>
              </select>
            </template>
          </div>

          <!-- OCR Result -->
          <div class="mt-3 pt-2 border-t border-midnight-700">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs text-midnight-500">OCR Result</span>
              <span
                v-if="getRegionConfidence(region.label)"
                class="text-xs text-midnight-600"
              >
                {{ getRegionConfidence(region.label) }}%
              </span>
            </div>
            
            <!-- Time display for time type -->
            <template v-if="region.region_type === 'time' && getResultTime(region.label)">
              <div class="font-mono text-sm p-2 rounded bg-midnight-900/50 text-electric-400">
                {{ getResultTime(region.label).formatted }}
              </div>
              <div class="text-xs text-midnight-600 mt-1">
                {{ getResultTime(region.label).minutes }}m {{ getResultTime(region.label).seconds }}s
                <span v-if="getResultTime(region.label).centiseconds">.{{ getResultTime(region.label).centiseconds }}cs</span>
                ({{ getResultTime(region.label).total_seconds.toFixed(2) }}s total)
              </div>
            </template>
            
            <!-- Default display for other types -->
            <template v-else>
              <div 
                class="font-mono text-sm p-2 rounded bg-midnight-900/50"
                :class="getResultText(region.label) ? 'text-electric-400' : 'text-midnight-600 italic'"
              >
                {{ getResultText(region.label) || 'No text detected' }}
              </div>
            </template>
          </div>
        </div>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <!-- Glyph Training Section -->
    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">
          Glyph Training
        </h3>
        <div class="flex items-center gap-2">
          <button 
            v-if="session?.glyphs?.length"
            class="text-xs text-electric-400 hover:text-electric-300 transition-colors"
            @click="openExportDialog"
          >
            Export
          </button>
          <button 
            class="text-xs text-electric-400 hover:text-electric-300 transition-colors"
            @click="openImportDialog"
          >
            Import
          </button>
          <button 
            v-if="session?.glyphs?.length"
            class="text-xs text-midnight-600 hover:text-ember-400 transition-colors"
            @click="handleClearGlyphs"
          >
            Clear All
          </button>
        </div>
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
          <option :value="null">
            Full processed frame
          </option>
          <option
            v-for="region in session?.ocr_regions"
            :key="region.id"
            :value="region.id"
          >
            {{ region.label }}
          </option>
        </select>
        <button
          :disabled="isDetecting"
          class="px-3 py-2 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-xs font-medium rounded transition-colors"
          @click="handleDetectGlyphs"
        >
          {{ isDetecting ? 'Detecting...' : 'Detect' }}
        </button>
      </div>

      <!-- Merge vertical option -->
      <label class="flex items-center gap-2 mb-3 text-xs text-midnight-400 cursor-pointer">
        <input
          v-model="mergeVertical"
          type="checkbox"
          class="w-3.5 h-3.5 rounded border-midnight-600 bg-midnight-900 text-electric-500 focus:ring-electric-500 focus:ring-offset-0"
        >
        <span>Auto-merge vertical (for ":" etc.)</span>
      </label>

      <!-- Detected glyphs for labeling -->
      <div
        v-if="detectedGlyphs.length"
        class="mb-4"
      >
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs text-midnight-500">
            Detected Glyphs ({{ detectedGlyphs.length }})
          </div>
          <div
            v-if="selectedCount > 0"
            class="text-xs text-electric-400"
          >
            {{ selectedCount }} selected
          </div>
        </div>

        <!-- Combine UI when multiple selected -->
        <div
          v-if="selectedCount >= 2"
          class="bg-electric-500/10 border border-electric-500/30 rounded-lg p-3 mb-3"
        >
          <div class="text-xs text-electric-400 mb-2">
            Combine {{ selectedCount }} glyphs into one:
          </div>
          <div class="flex gap-2">
            <input
              v-model="combineLabel"
              maxlength="3"
              placeholder="Label (e.g. :)"
              class="flex-1 bg-midnight-900 border border-midnight-700 rounded px-2 py-1.5 text-xs text-midnight-200 focus:outline-none focus:border-electric-500"
              @keyup.enter="handleCombineSelected"
            >
            <button
              :disabled="!combineLabel"
              class="px-3 py-1.5 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-xs font-medium rounded transition-colors"
              @click="handleCombineSelected"
            >
              Combine
            </button>
            <button
              class="px-2 py-1.5 bg-midnight-700 hover:bg-midnight-600 text-midnight-300 text-xs rounded transition-colors"
              @click="clearSelection"
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
            class="flex flex-col rounded p-2 text-center cursor-pointer transition-all"
            :class="isGlyphSelected(glyph.index)
              ? 'bg-electric-500/20 border-2 border-electric-500'
              : 'bg-midnight-800 border-2 border-transparent hover:border-midnight-600'"
            @click="toggleGlyphSelection(glyph.index)"
          >
            <img
              :src="templateToDataUrl(glyph.template)"
              class="w-8 h-12 mx-auto object-contain bg-white rounded"
              style="image-rendering: pixelated;"
            >
            <div class="text-[10px] text-midnight-500 h-4 flex items-center justify-center">
              <span v-if="glyph.merged_count > 1">(merged: {{ glyph.merged_count }})</span>
            </div>
            <input
              v-model="glyphLabels[glyph.index]"
              maxlength="2"
              placeholder="?"
              class="w-full bg-midnight-900 border border-midnight-700 rounded px-1 py-0.5 text-xs text-center text-midnight-200 focus:outline-none focus:border-electric-500"
              @click.stop
              @keyup.enter="handleSaveGlyph(glyph)"
            >
            <div class="flex gap-1 mt-1">
              <button
                :disabled="!glyphLabels[glyph.index]"
                class="flex-1 px-1 py-0.5 bg-electric-500/20 hover:bg-electric-500/30 disabled:bg-midnight-700/50 text-electric-400 disabled:text-midnight-600 text-xs rounded"
                @click.stop="handleSaveGlyph(glyph)"
              >
                Save
              </button>
              <button
                class="px-1 py-0.5 bg-midnight-700 hover:bg-midnight-600 text-midnight-400 text-xs rounded"
                title="Ignore this glyph"
                @click.stop="handleIgnoreGlyph(glyph)"
              >
                Ign
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Saved glyphs -->
      <div v-if="session?.glyphs?.length">
        <div class="text-xs text-midnight-500 mb-2">
          Trained Glyphs ({{ session.glyphs.length }})
        </div>
        <div class="flex flex-wrap gap-2">
          <div 
            v-for="glyph in session.glyphs" 
            :key="glyph.id"
            class="rounded p-2 text-center relative group"
            :class="glyph.ignored ? 'bg-midnight-900/50 border border-midnight-700' : 'bg-midnight-800'"
          >
            <img 
              :src="templateToDataUrl(glyph.template)" 
              class="w-6 h-9 mx-auto mb-1 object-contain rounded"
              :class="glyph.ignored ? 'bg-midnight-700 opacity-50' : 'bg-white'"
              style="image-rendering: pixelated;"
            >
            <div 
              class="text-xs font-mono"
              :class="glyph.ignored ? 'text-midnight-600 line-through' : 'text-electric-400'"
            >
              {{ glyph.ignored ? 'IGN' : glyph.char }}
            </div>
            <div class="absolute -top-1 -right-1 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                class="w-4 h-4 bg-midnight-600 hover:bg-midnight-500 text-midnight-300 rounded-full text-xs flex items-center justify-center"
                :title="glyph.ignored ? 'Un-ignore' : 'Ignore'"
                @click="handleToggleIgnored(glyph.id, glyph.ignored)"
              >
                {{ glyph.ignored ? '✓' : '−' }}
              </button>
              <button
                class="w-4 h-4 bg-ember-500 text-white rounded-full text-xs flex items-center justify-center"
                @click="handleDeleteGlyph(glyph.id)"
              >
                ×
              </button>
            </div>
          </div>
        </div>
      </div>

      <div
        v-else-if="!detectedGlyphs.length"
        class="text-sm text-midnight-600 text-center py-4"
      >
        No glyphs trained yet. Click "Detect" to find characters.
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-4">
        Info
      </h3>
      
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
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-3">
        API Endpoints
      </h3>
      <div class="space-y-2 text-xs">
        <div class="bg-midnight-800/50 rounded p-2 font-mono text-midnight-400">
          GET /ocr/{{ session?.id }}
        </div>
        <p class="text-midnight-600">
          Returns all regions with OCR results as JSON
        </p>
        
        <div class="bg-midnight-800/50 rounded p-2 font-mono text-midnight-400">
          GET /ocr/{{ session?.id }}/{'{region_name}'}
        </div>
        <p class="text-midnight-600">
          Returns plain text result for a specific region
        </p>
      </div>
    </section>

    <!-- Export Dialog -->
    <div
      v-if="showExportDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    >
      <div class="bg-midnight-900 rounded-lg p-5 w-80 border border-midnight-700">
        <h4 class="text-sm font-medium text-midnight-200 mb-4">
          Export Glyphs
        </h4>
        <input
          v-model="exportName"
          placeholder="Glyph set name"
          class="w-full bg-midnight-800 border border-midnight-700 rounded px-3 py-2 text-sm text-midnight-200 focus:outline-none focus:border-electric-500 mb-4"
          @keyup.enter="handleExportGlyphs"
        >
        <div class="flex justify-end gap-2">
          <button
            class="px-3 py-1.5 text-sm text-midnight-400 hover:text-midnight-300"
            @click="showExportDialog = false"
          >
            Cancel
          </button>
          <button
            :disabled="!exportName.trim()"
            class="px-3 py-1.5 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-sm rounded"
            @click="handleExportGlyphs"
          >
            Export
          </button>
        </div>
      </div>
    </div>

    <!-- Import Dialog -->
    <div
      v-if="showImportDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    >
      <div class="bg-midnight-900 rounded-lg p-5 w-96 border border-midnight-700 max-h-[80vh] flex flex-col">
        <h4 class="text-sm font-medium text-midnight-200 mb-4">
          Import Glyphs
        </h4>
        
        <div
          v-if="!glyphSets.length"
          class="text-sm text-midnight-500 text-center py-4"
        >
          No glyph sets saved yet. Export glyphs from a session first.
        </div>
        
        <div
          v-else
          class="flex-1 overflow-y-auto space-y-2 mb-4"
        >
          <div
            v-for="gs in glyphSets"
            :key="gs.id"
            class="p-3 rounded-lg cursor-pointer transition-all"
            :class="selectedImportSet === gs.id 
              ? 'bg-electric-500/20 border border-electric-500' 
              : 'bg-midnight-800 border border-transparent hover:border-midnight-600'"
            @click="selectedImportSet = gs.id"
          >
            <div class="flex items-center justify-between">
              <div>
                <div class="text-sm text-midnight-200">
                  {{ gs.name }}
                </div>
                <div class="text-xs text-midnight-500">
                  {{ gs.glyph_count }} glyphs
                </div>
              </div>
              <button
                class="p-1 text-midnight-600 hover:text-ember-400 transition-colors"
                @click.stop="handleDeleteGlyphSet(gs.id)"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="h-4 w-4"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fill-rule="evenodd"
                    d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                    clip-rule="evenodd"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <label
          v-if="glyphSets.length"
          class="flex items-center gap-2 mb-4 text-xs text-midnight-400 cursor-pointer"
        >
          <input
            v-model="importReplace"
            type="checkbox"
            class="w-3.5 h-3.5 rounded border-midnight-600 bg-midnight-900 text-electric-500 focus:ring-electric-500 focus:ring-offset-0"
          >
          <span>Replace existing glyphs (instead of adding)</span>
        </label>

        <div class="flex justify-end gap-2">
          <button
            class="px-3 py-1.5 text-sm text-midnight-400 hover:text-midnight-300"
            @click="showImportDialog = false; selectedImportSet = null"
          >
            Cancel
          </button>
          <button
            :disabled="!selectedImportSet"
            class="px-3 py-1.5 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 text-midnight-950 disabled:text-midnight-500 text-sm rounded"
            @click="handleImportGlyphs"
          >
            Import
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
