import { defineConfig } from 'vite'
import solid from 'vite-plugin-solid'

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/ocr/' : '/',
  plugins: [solid()],
}))
