// desktop/src/renderer/components/AvatarSwitch.tsx

import { Avatar, type CharacterState } from "./Avatar";
import { Live2DAvatar } from "./Live2DAvatar";

export type DisplayMode = "2d" | "live2d";

interface AvatarSwitchProps {
  characterDir: string;
  live2dModelPath?: string;
  live2dScale?: number;
  state: CharacterState;
  onClick: () => void;
  mode: DisplayMode;
}

export function getStoredMode(key: string): DisplayMode {
  try {
    const stored = localStorage.getItem(`nomi-display-mode-${key}`);
    if (stored === "live2d") return "live2d";
  } catch {}
  return "2d";
}

export function storeMode(key: string, mode: DisplayMode): void {
  try {
    localStorage.setItem(`nomi-display-mode-${key}`, mode);
  } catch {}
}

export function AvatarSwitch({
  characterDir,
  live2dModelPath,
  live2dScale,
  state,
  onClick,
  mode,
}: AvatarSwitchProps) {
  return (
    <div onClick={onClick}>
      {mode === "live2d" && live2dModelPath ? (
        <Live2DAvatar
          modelPath={live2dModelPath}
          state={state}
          modelScale={live2dScale}
        />
      ) : (
        <Avatar
          characterDir={characterDir}
          state={state}
          onClick={() => {}}
        />
      )}
    </div>
  );
}
