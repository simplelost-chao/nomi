import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nomi", {
  toggleExpand: () => ipcRenderer.invoke("toggle-expand"),
  minimize: () => ipcRenderer.invoke("minimize-to-tray"),
  getBackendStatus: () => ipcRenderer.invoke("get-backend-status"),
  onBackendReady: (callback: () => void) => {
    ipcRenderer.on("backend-ready", callback);
    return () => { ipcRenderer.removeListener("backend-ready", callback); };
  },

  // Agent APIs
  agent: {
    getConfig: () => ipcRenderer.invoke("agent:get-config"),
    updateConfig: (partial: Record<string, unknown>) => ipcRenderer.invoke("agent:update-config", partial),
    getStatus: () => ipcRenderer.invoke("agent:get-status"),
    start: () => ipcRenderer.invoke("agent:start"),
    stop: () => ipcRenderer.invoke("agent:stop"),
    onReaction: (callback: (data: unknown) => void) => {
      const handler = (_e: unknown, data: unknown) => callback(data);
      ipcRenderer.on("agent:reaction", handler);
      return () => { ipcRenderer.removeListener("agent:reaction", handler); };
    },
    onStatus: (callback: (data: unknown) => void) => {
      const handler = (_e: unknown, data: unknown) => callback(data);
      ipcRenderer.on("agent:status", handler);
      return () => { ipcRenderer.removeListener("agent:status", handler); };
    },
    onActionResult: (callback: (data: unknown) => void) => {
      const handler = (_e: unknown, data: unknown) => callback(data);
      ipcRenderer.on("agent:action-result", handler);
      return () => { ipcRenderer.removeListener("agent:action-result", handler); };
    },
    executeAction: (action: { type: string; params: Record<string, string> }) =>
      ipcRenderer.invoke("agent:execute-action", action),
    getDesktopContext: () => ipcRenderer.invoke("agent:get-desktop-context") as Promise<{ activeApp: string; windowTitle: string; screenshot: string }>,
  },
});
