<script setup>
defineProps({
  session: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['clear-perspective'])

function clearPerspective() {
  emit('clear-perspective')
}
</script>

<template>
  <div class="p-5 space-y-6">
    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-4">
        Perspective Correction
      </h3>
      
      <div class="space-y-4">
        <div class="flex items-center justify-between text-sm">
          <span class="text-midnight-400">Status</span>
          <span :class="session?.perspective_points ? 'text-electric-400' : 'text-midnight-600'">
            {{ session?.perspective_points ? '4 points set' : 'Not configured' }}
          </span>
        </div>

        <div
          v-if="session?.perspective_output_size"
          class="flex items-center justify-between text-sm"
        >
          <span class="text-midnight-400">Output Resolution</span>
          <span class="text-midnight-300 font-mono">
            {{ session.perspective_output_size[0] }} × {{ session.perspective_output_size[1] }}
          </span>
        </div>
        
        <button
          v-if="session?.perspective_points"
          class="w-full py-2 px-3 text-sm bg-midnight-800 hover:bg-midnight-700 text-midnight-300 rounded-lg transition-colors"
          @click="clearPerspective"
        >
          Clear Points
        </button>
      </div>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-3">
        Instructions
      </h3>
      <ul class="text-xs text-midnight-600 space-y-2">
        <li class="flex gap-2">
          <span class="text-electric-400">1.</span>
          Click 4 points on the video in order: top-left, top-right, bottom-right, bottom-left
        </li>
        <li class="flex gap-2">
          <span class="text-electric-400">2.</span>
          Drag points to adjust after placing
        </li>
        <li class="flex gap-2">
          <span class="text-electric-400">3.</span>
          The area inside will be transformed to a rectangle
        </li>
      </ul>
    </section>

    <div class="border-t border-midnight-800" />

    <section>
      <h3 class="text-xs uppercase tracking-widest text-midnight-500 mb-3">
        Point Order
      </h3>
      <div class="grid grid-cols-2 gap-2 text-xs">
        <div class="flex items-center gap-2">
          <div class="w-3 h-3 rounded-full bg-[#00d9ff]" />
          <span class="text-midnight-400">TL - Top Left</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-3 h-3 rounded-full bg-[#00ff9d]" />
          <span class="text-midnight-400">TR - Top Right</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-3 h-3 rounded-full bg-[#ff6b6b]" />
          <span class="text-midnight-400">BR - Bottom Right</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-3 h-3 rounded-full bg-[#ffb347]" />
          <span class="text-midnight-400">BL - Bottom Left</span>
        </div>
      </div>
    </section>
  </div>
</template>
