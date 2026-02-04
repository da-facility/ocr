<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  src: {
    type: String,
    default: ''
  }
})

const loaded = ref(false)
const error = ref(false)

function handleLoad() {
  loaded.value = true
  error.value = false
}

function handleError() {
  error.value = true
  loaded.value = false
}

watch(() => props.src, () => {
  loaded.value = false
  error.value = false
})
</script>

<template>
  <div class="relative w-full h-full flex items-center justify-center bg-midnight-950 overflow-hidden">
    <div 
      v-if="!loaded && !error" 
      class="absolute inset-0 flex items-center justify-center"
    >
      <div class="flex flex-col items-center gap-3">
        <div class="w-8 h-8 border-2 border-electric-400 border-t-transparent rounded-full animate-spin" />
        <span class="text-midnight-500 text-sm">Connecting to stream...</span>
      </div>
    </div>

    <div 
      v-if="error" 
      class="absolute inset-0 flex items-center justify-center"
    >
      <div class="text-center">
        <div class="text-6xl text-midnight-800 mb-4">
          ◎
        </div>
        <div class="text-midnight-500">
          Stream unavailable
        </div>
      </div>
    </div>

    <img
      v-if="src"
      :src="src"
      :class="[
        'max-w-full max-h-full w-auto h-auto object-contain transition-opacity duration-300',
        loaded ? 'opacity-100' : 'opacity-0'
      ]"
      alt="Camera stream"
      @load="handleLoad"
      @error="handleError"
    >
  </div>
</template>
