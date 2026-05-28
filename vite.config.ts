import { defineConfig } from 'vite'
import solid from 'vite-plugin-solid'

export default defineConfig(({ command }) => ({
  base: process.env.VITE_BASE ?? (command === 'build' ? '/ocr/' : '/'),
  plugins: [solid()],
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        paddleTest: 'paddle-test.html',
      },
    },
  },
}))
