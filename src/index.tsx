/* @refresh reload */
import { render } from 'solid-js/web'
import './index.css'
import App from './App.tsx'
import { registerServiceWorker } from './lib/pwa.ts'

const root = document.getElementById('root')

registerServiceWorker()
render(() => <App />, root!)
