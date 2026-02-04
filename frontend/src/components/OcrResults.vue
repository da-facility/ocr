<script setup>
import { computed } from 'vue'

const props = defineProps({
  results: {
    type: Object,
    default: () => ({})
  },
  regions: {
    type: Array,
    default: () => []
  }
})

const allRegionNames = computed(() => {
  const fromResults = Object.keys(props.results)
  const fromRegions = props.regions.map(r => r.label)
  const all = new Set([...fromResults, ...fromRegions])
  return Array.from(all).filter(n => n !== '_full')
})

const hasAnyRegions = computed(() => allRegionNames.value.length > 0 || '_full' in props.results)

function getRegionText(regionName) {
  const result = props.results[regionName]
  if (!result) return ''
  return result.text || ''
}

function getRegionConfidence(regionName) {
  const result = props.results[regionName]
  if (!result || !Array.isArray(result.detections) || result.detections.length === 0) return null
  const avg = result.detections.reduce((sum, d) => sum + d.confidence, 0) / result.detections.length
  return Math.round(avg * 100)
}

function hasDetections(regionName) {
  const result = props.results[regionName]
  return result && Array.isArray(result.detections) && result.detections.length > 0
}
</script>

<template>
  <div class="bg-midnight-900/50 backdrop-blur">
    <div class="px-4 py-2 border-b border-midnight-800 flex items-center justify-between">
      <h3 class="text-xs uppercase tracking-widest text-midnight-500">OCR Results</h3>
      <span v-if="allRegionNames.length" class="text-xs text-midnight-600">
        {{ allRegionNames.length }} region{{ allRegionNames.length !== 1 ? 's' : '' }}
      </span>
    </div>
    
    <div class="p-4 min-h-[80px] max-h-[200px] overflow-y-auto">
      <div v-if="!hasAnyRegions" class="text-midnight-600 text-sm text-center py-4">
        No OCR regions defined
      </div>
      
      <div v-else class="space-y-2">
        <!-- Full frame results if no regions -->
        <div 
          v-if="'_full' in results && allRegionNames.length === 0"
          class="bg-midnight-800/50 rounded-lg p-3 border border-midnight-700"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-mono text-midnight-400">Full Frame</span>
            <span v-if="getRegionConfidence('_full')" class="text-xs text-midnight-500">
              {{ getRegionConfidence('_full') }}% avg
            </span>
          </div>
          <div class="font-mono text-sm leading-relaxed" :class="hasDetections('_full') ? 'text-midnight-200' : 'text-midnight-600 italic'">
            {{ getRegionText('_full') || 'No text detected' }}
          </div>
        </div>

        <!-- Region results -->
        <div 
          v-for="regionName in allRegionNames" 
          :key="regionName"
          class="bg-midnight-800/50 rounded-lg p-3 border border-midnight-700"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-mono text-electric-400">{{ regionName }}</span>
            <span v-if="getRegionConfidence(regionName)" class="text-xs text-midnight-500">
              {{ getRegionConfidence(regionName) }}% avg
            </span>
            <span v-else class="text-xs text-midnight-600">—</span>
          </div>
          <div class="font-mono text-sm leading-relaxed" :class="hasDetections(regionName) ? 'text-midnight-200' : 'text-midnight-600 italic'">
            {{ getRegionText(regionName) || 'No text detected' }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
