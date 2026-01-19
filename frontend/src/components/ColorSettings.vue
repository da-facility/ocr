<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  session: Object,
  colorPickerMode: Boolean,
  layout: {
    type: String,
    default: 'vertical'
  }
})

const emit = defineEmits(['toggle-picker', 'add-filter', 'update-filter', 'delete-filter', 'clear-filters', 'update-morphology', 'toggle-layout'])

const erosionKernel = ref(0)
const dilationKernel = ref(0)

let debounceTimer = null

function initFromSession() {
  erosionKernel.value = props.session?.erosion_kernel ?? 0
  dilationKernel.value = props.session?.dilation_kernel ?? 0
}

function emitMorphology() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    emit('update-morphology', erosionKernel.value, dilationKernel.value)
  }, 300)
}

function bgrToHex(bgr) {
  const [b, g, r] = bgr
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

function bgrToRgbString(bgr) {
  const [b, g, r] = bgr
  return `rgb(${r}, ${g}, ${b})`
}

watch(() => props.session, initFromSession, { immediate: true })
</script>

<template>
  <div class="p-5 space-y-6">
    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">Layout</h3>
      </div>

      <div class="flex gap-2">
        <button
          @click="$emit('toggle-layout')"
          :class="[
            'flex-1 py-2 px-3 text-xs font-medium rounded-lg transition-all flex items-center justify-center gap-2',
            layout === 'vertical' 
              ? 'bg-electric-500 text-midnight-950' 
              : 'bg-midnight-800 hover:bg-midnight-700 text-midnight-400'
          ]"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          Stacked
        </button>
        <button
          @click="$emit('toggle-layout')"
          :class="[
            'flex-1 py-2 px-3 text-xs font-medium rounded-lg transition-all flex items-center justify-center gap-2',
            layout === 'horizontal' 
              ? 'bg-electric-500 text-midnight-950' 
              : 'bg-midnight-800 hover:bg-midnight-700 text-midnight-400'
          ]"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" />
          </svg>
          Side by Side
        </button>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">Color Picker</h3>
      </div>

      <button
        @click="$emit('toggle-picker')"
        :class="[
          'w-full py-3 px-4 text-sm font-medium rounded-lg transition-all duration-200',
          colorPickerMode 
            ? 'bg-electric-500 text-midnight-950 shadow-lg shadow-electric-500/20' 
            : 'bg-midnight-800 hover:bg-midnight-700 text-midnight-300'
        ]"
      >
        <span v-if="colorPickerMode">Click on video to pick color...</span>
        <span v-else>Pick Color from Video</span>
      </button>

      <p class="text-xs text-midnight-600 mt-2">
        Picks color from the perspective-corrected stream
      </p>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">Color Filters</h3>
        <button 
          v-if="session?.color_filters?.length"
          @click="$emit('clear-filters')"
          class="text-xs text-midnight-600 hover:text-ember-400 transition-colors"
        >
          Clear All
        </button>
      </div>

      <div v-if="!session?.color_filters?.length" class="text-sm text-midnight-600 text-center py-4">
        No colors added yet
      </div>

      <div v-else class="space-y-3">
        <div 
          v-for="filter in session.color_filters" 
          :key="filter.id"
          class="bg-midnight-800/50 rounded-lg p-3 border border-midnight-700"
        >
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div 
                class="w-6 h-6 rounded border border-midnight-600"
                :style="{ backgroundColor: bgrToRgbString(filter.bgr) }"
              />
              <span class="text-xs font-mono text-midnight-400">{{ bgrToHex(filter.bgr) }}</span>
            </div>
            <button
              @click="$emit('delete-filter', filter.id)"
              class="p-1 text-midnight-600 hover:text-ember-400 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

          <div class="space-y-2">
            <div>
              <div class="flex justify-between text-xs text-midnight-500 mb-1">
                <span>B Tolerance</span>
                <span class="font-mono">±{{ filter.tolerance[0] }}</span>
              </div>
              <input
                type="range"
                :value="filter.tolerance[0]"
                @input="(e) => $emit('update-filter', filter.id, [parseInt(e.target.value), filter.tolerance[1], filter.tolerance[2]])"
                min="0"
                max="128"
                class="w-full accent-blue-400"
              />
            </div>
            <div>
              <div class="flex justify-between text-xs text-midnight-500 mb-1">
                <span>G Tolerance</span>
                <span class="font-mono">±{{ filter.tolerance[1] }}</span>
              </div>
              <input
                type="range"
                :value="filter.tolerance[1]"
                @input="(e) => $emit('update-filter', filter.id, [filter.tolerance[0], parseInt(e.target.value), filter.tolerance[2]])"
                min="0"
                max="128"
                class="w-full accent-green-400"
              />
            </div>
            <div>
              <div class="flex justify-between text-xs text-midnight-500 mb-1">
                <span>R Tolerance</span>
                <span class="font-mono">±{{ filter.tolerance[2] }}</span>
              </div>
              <input
                type="range"
                :value="filter.tolerance[2]"
                @input="(e) => $emit('update-filter', filter.id, [filter.tolerance[0], filter.tolerance[1], parseInt(e.target.value)])"
                min="0"
                max="128"
                class="w-full accent-red-400"
              />
            </div>
          </div>
        </div>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs uppercase tracking-widest text-midnight-500">Morphology</h3>
        <button 
          @click="erosionKernel = 0; dilationKernel = 0; emitMorphology()"
          class="text-xs text-midnight-600 hover:text-midnight-400 transition-colors"
        >
          Turn Off
        </button>
      </div>

      <div class="space-y-4">
        <div>
          <div class="flex justify-between text-xs text-midnight-500 mb-1">
            <span>Erosion</span>
            <span class="font-mono">{{ erosionKernel === 0 ? 'Off' : erosionKernel + 'px' }}</span>
          </div>
          <input
            type="range"
            v-model.number="erosionKernel"
            @input="emitMorphology"
            min="0"
            max="15"
            class="w-full accent-electric-500"
          />
        </div>

        <div>
          <div class="flex justify-between text-xs text-midnight-500 mb-1">
            <span>Dilation</span>
            <span class="font-mono">{{ dilationKernel === 0 ? 'Off' : dilationKernel + 'px' }}</span>
          </div>
          <input
            type="range"
            v-model.number="dilationKernel"
            @input="emitMorphology"
            min="0"
            max="15"
            class="w-full accent-electric-500"
          />
        </div>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-3">Pipeline Info</h3>
      <p class="text-xs text-midnight-600">
        Processing order: Perspective → Color Filters → Morphology
      </p>
      <p class="text-xs text-midnight-600 mt-2">
        If no color filters are set, only perspective correction is applied.
      </p>
    </section>
  </div>
</template>

<style scoped>
input[type="range"] {
  @apply h-2 bg-midnight-800 rounded-lg appearance-none cursor-pointer;
}

input[type="range"]::-webkit-slider-thumb {
  @apply appearance-none w-4 h-4 rounded-full cursor-pointer;
}

input[type="range"].accent-electric-500::-webkit-slider-thumb {
  @apply bg-electric-400;
}

input[type="range"].accent-blue-400::-webkit-slider-thumb {
  @apply bg-blue-400;
}

input[type="range"].accent-green-400::-webkit-slider-thumb {
  @apply bg-green-400;
}

input[type="range"].accent-red-400::-webkit-slider-thumb {
  @apply bg-red-400;
}
</style>
