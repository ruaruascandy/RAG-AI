const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  openPathDialog: (options) => ipcRenderer.invoke('open-path-dialog', options)
});
