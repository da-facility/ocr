const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronOutput', {
  pickDirectory: () => ipcRenderer.invoke('output:pick-directory'),
  pickFile: () => ipcRenderer.invoke('output:pick-file'),
  writeFile: (path, content) => ipcRenderer.invoke('output:write-file', { path, content }),
  writeDirectoryFile: (directoryPath, fileName, content) =>
    ipcRenderer.invoke('output:write-directory-file', { directoryPath, fileName, content }),
})
