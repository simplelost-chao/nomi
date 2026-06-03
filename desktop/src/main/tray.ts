import { Tray, Menu, nativeImage, app } from "electron";
import path from "path";
import { showWindow, hideWindow, getMainWindow } from "./index";

let tray: Tray | null = null;

export function setupTray(): void {
  const iconPath = path.join(app.getAppPath(), "assets", "tray-icon.png");
  let icon: Electron.NativeImage;
  try {
    icon = nativeImage.createFromPath(iconPath);
    icon = icon.resize({ width: 18, height: 18 });
    icon.setTemplateImage(true);
  } catch {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip("Nomi Companion");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "显示/隐藏角色",
      click: () => {
        const win = getMainWindow();
        if (win?.isVisible()) {
          hideWindow();
        } else {
          showWindow();
        }
      },
    },
    { type: "separator" },
    {
      label: "退出 Nomi",
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  tray.on("click", () => {
    const win = getMainWindow();
    if (win?.isVisible()) {
      hideWindow();
    } else {
      showWindow();
    }
  });
}
