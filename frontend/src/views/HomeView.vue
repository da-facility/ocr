<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listCameras, listSessions, createSession, deleteSession } from '../api'

const router = useRouter()
const cameras = ref([])
const sessions = ref([])
const selectedCamera = ref(null)
const camerasLoading = ref(false)
const sessionsLoading = ref(false)
const creatingSession = ref(false)
const error = ref(null)

async function loadCameras() {
  camerasLoading.value = true
  error.value = null
  try {
    const cameraList = await listCameras()
    cameras.value = cameraList.map(cam => {
      const hasIds = cam.pid !== null && cam.pid !== undefined &&
        cam.vid !== null && cam.vid !== undefined
      const idLabel = hasIds ? ` (${cam.pid}:${cam.vid})` : ''
      return {
        ...cam,
        display_name: `${cam.name}${idLabel}`
      }
    })
    if (cameraList.length > 0 && selectedCamera.value === null) {
      selectedCamera.value = cameraList[0].index
    }
  } catch (err) {
    console.error(err)
    error.value = 'Failed to load cameras. Is the backend running?'
  } finally {
    camerasLoading.value = false
  }
}

async function loadSessions() {
  sessionsLoading.value = true
  error.value = null
  try {
    sessions.value = await listSessions()
  } catch (err) {
    console.error(err)
    error.value = 'Failed to load sessions. Is the backend running?'
  } finally {
    sessionsLoading.value = false
  }
}

function matchesSessionCamera(session, camera) {
  const sessionName = session.camera_device_name || session.camera_name || ''
  const hasVid = session.camera_vid !== null && session.camera_vid !== undefined
  const hasPid = session.camera_pid !== null && session.camera_pid !== undefined
  if (hasVid && hasPid) {
    return camera.vid === session.camera_vid &&
      camera.pid === session.camera_pid &&
      camera.name === sessionName
  }
  return camera.name === sessionName
}

function resolveSessionCamera(session) {
  if (camerasLoading.value) {
    return { missing: false, reason: '' }
  }
  const matches = cameras.value.filter(camera => matchesSessionCamera(session, camera))
  if (matches.length === 0) {
    return { missing: true, reason: 'Camera missing or disconnected.' }
  }
  if (matches.length === 1) {
    return { missing: false, reason: '' }
  }
  const indexMatch = matches.find(camera => camera.index === session.camera_index)
  if (indexMatch) {
    return { missing: false, reason: '' }
  }
  return { missing: true, reason: 'Multiple matching cameras found.' }
}

const sessionsWithStatus = computed(() => {
  return sessions.value.map(session => {
    const status = resolveSessionCamera(session)
    return {
      ...session,
      missingCamera: status.missing,
      missingReason: status.reason
    }
  })
})

async function handleCreateSession() {
  if (selectedCamera.value === null) return
  creatingSession.value = true
  try {
    const cam = cameras.value.find(c => c.index === selectedCamera.value)
    if (!cam) {
      error.value = 'Selected camera not found'
      creatingSession.value = false
      return
    }
    const session = await createSession(cam)
    router.push(`/session/${session.id}`)
  } catch (err) {
    console.error(err)
    error.value = 'Failed to create session'
    creatingSession.value = false
  }
}

async function handleDeleteSession(id) {
  if (!confirm('Delete this session?')) return
  try {
    await deleteSession(id)
    await loadSessions()
  } catch (err) {
    console.error(err)
    error.value = 'Failed to delete session'
  }
}

function openSession(id) {
  router.push(`/session/${id}`)
}

function openSessionIfAvailable(session) {
  if (session.missingCamera) {
    return
  }
  openSession(session.id)
}

onMounted(() => {
  loadCameras()
  loadSessions()
})
</script>

<template>
  <div class="min-h-screen p-8">
    <header class="max-w-6xl mx-auto mb-12">
      <h1 class="text-4xl font-light tracking-tight">
        <span class="text-electric-400">OCR</span>
        <span class="text-midnight-400 ml-2">Stream</span>
      </h1>
      <p class="text-midnight-500 mt-2 text-sm tracking-wide">
        Real-time optical character recognition
      </p>
    </header>

    <main class="max-w-6xl mx-auto">
      <div
        v-if="error"
        class="mb-8 p-4 bg-ember-500/10 border border-ember-500/30 rounded-lg text-ember-400"
      >
        {{ error }}
      </div>

      <section class="mb-12">
        <h2 class="text-sm uppercase tracking-widest text-midnight-500 mb-6">
          Create Session
        </h2>
        
        <div class="bg-midnight-900/50 border border-midnight-800 rounded-xl p-6 backdrop-blur">
          <div class="flex items-end gap-4">
            <div class="flex-1">
              <label class="block text-xs uppercase tracking-wider text-midnight-500 mb-2">
                Camera Device
              </label>
              <select 
                v-model="selectedCamera"
                :disabled="cameras.length === 0 || camerasLoading"
                class="w-full bg-midnight-800 border border-midnight-700 rounded-lg px-4 py-3 text-midnight-100 focus:outline-none focus:border-electric-500 transition-colors"
              >
                <option
                  v-if="camerasLoading"
                  :value="null"
                >
                  Loading cameras...
                </option>
                <option
                  v-else-if="cameras.length === 0"
                  :value="null"
                >
                  No cameras available
                </option>
                <option
                  v-for="cam in cameras"
                  :key="cam.index"
                  :value="cam.index"
                >
                  {{ cam.display_name }}
                </option>
              </select>
            </div>
            <button
              :disabled="creatingSession || selectedCamera === null || camerasLoading"
              class="px-6 py-3 bg-electric-500 hover:bg-electric-400 disabled:bg-midnight-700 disabled:text-midnight-500 text-midnight-950 font-medium rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-electric-500/20"
              @click="handleCreateSession"
            >
              <span v-if="creatingSession">Creating...</span>
              <span v-else>Create Session</span>
            </button>
          </div>
        </div>
      </section>

      <section>
        <h2 class="text-sm uppercase tracking-widest text-midnight-500 mb-6">
          Active Sessions
        </h2>
        
        <div
          v-if="sessionsLoading"
          class="text-center py-16 text-midnight-600"
        >
          <div class="text-6xl mb-4 opacity-30">
            ◎
          </div>
          <p>Loading sessions...</p>
        </div>
        <div
          v-else-if="sessionsWithStatus.length === 0"
          class="text-center py-16 text-midnight-600"
        >
          <div class="text-6xl mb-4 opacity-30">
            ◎
          </div>
          <p>No active sessions</p>
        </div>

        <div
          v-else
          class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          <div
            v-for="session in sessionsWithStatus"
            :key="session.id"
            class="group bg-midnight-900/50 border border-midnight-800 rounded-xl p-5 transition-all duration-200"
            :class="session.missingCamera
              ? 'opacity-60 cursor-not-allowed'
              : 'hover:border-electric-500/50 cursor-pointer hover:shadow-lg hover:shadow-electric-500/5'"
            @click="openSessionIfAvailable(session)"
          >
            <div
              v-if="session.missingCamera"
              class="mb-3 px-3 py-2 rounded-lg border border-ember-500/30 bg-ember-500/10 text-ember-400 text-xs"
            >
              {{ session.missingReason }}
            </div>
            <div class="flex items-start justify-between mb-4">
              <div>
                <div class="text-xs text-midnight-500 uppercase tracking-wider">
                  Session
                </div>
                <div class="text-xl font-mono text-electric-400">
                  {{ session.id }}
                </div>
              </div>
              <button
                class="p-2 text-midnight-600 hover:text-ember-400 hover:bg-ember-500/10 rounded-lg transition-colors"
                @click.stop="handleDeleteSession(session.id)"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="h-4 w-4"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fill-rule="evenodd"
                    d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"
                    clip-rule="evenodd"
                  />
                </svg>
              </button>
            </div>
            
            <div class="space-y-2 text-sm">
              <div class="flex justify-between">
                <span class="text-midnight-500">Camera</span>
                <span class="text-midnight-300 truncate ml-2">{{ session.camera_name || `Camera ${session.camera_index}` }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-midnight-500">Perspective</span>
                <span :class="session.perspective_points ? 'text-electric-400' : 'text-midnight-600'">
                  {{ session.perspective_points ? '4 points set' : 'Not configured' }}
                </span>
              </div>
            </div>

            <div class="mt-4 pt-4 border-t border-midnight-800 flex items-center justify-between">
              <span class="text-xs text-midnight-600">Click to open</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                class="h-4 w-4 text-midnight-600 group-hover:text-electric-400 transition-colors"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fill-rule="evenodd"
                  d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"
                  clip-rule="evenodd"
                />
              </svg>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
