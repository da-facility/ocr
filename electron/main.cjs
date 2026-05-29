const { app, BrowserWindow, dialog, ipcMain, session } = require('electron')
const fs = require('node:fs/promises')
const path = require('node:path')

function outputName(filePath) {
  return path.basename(filePath)
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: '#111111',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.cjs'),
      sandbox: true,
    },
  })

  window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(['camera', 'media'].includes(permission))
  })

  ipcMain.handle('output:pick-directory', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory', 'createDirectory'],
      title: 'Choose OCR output folder',
    })

    if (result.canceled || result.filePaths.length === 0) {
      return null
    }

    const selected = result.filePaths[0]
    return { path: selected, name: outputName(selected) }
  })

  ipcMain.handle('output:pick-file', async () => {
    const result = await dialog.showSaveDialog({
      title: 'Choose OCR output file',
      defaultPath: 'ocr-live.txt',
      filters: [{ name: 'Text file', extensions: ['txt'] }],
    })

    if (result.canceled || !result.filePath) {
      return null
    }

    return { path: result.filePath, name: outputName(result.filePath) }
  })

  ipcMain.handle('output:write-file', async (_event, { path: filePath, content }) => {
    await fs.mkdir(path.dirname(filePath), { recursive: true })
    await fs.writeFile(filePath, content, 'utf8')
  })

  ipcMain.handle('output:write-directory-file', async (_event, { directoryPath, fileName, content }) => {
    await fs.mkdir(directoryPath, { recursive: true })
    await fs.writeFile(path.join(directoryPath, fileName), content, 'utf8')
  })

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
