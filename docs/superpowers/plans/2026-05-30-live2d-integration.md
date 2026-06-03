# Live2D Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Live2D character rendering with TTS lip-sync as an alternative display mode alongside existing 2D PNG avatars in the desktop companion app.

**Architecture:** New `AvatarSwitch` wrapper component manages 2D/Live2D toggle. `Live2DAvatar` renders a PixiJS canvas with pixi-live2d-display. `LipSyncAnalyzer` extracts audio amplitude via Web Audio API to drive mouth parameters. `api.ts` gains `fetchTtsBlob()` to separate TTS fetch from playback, enabling Live2D mode to control audio.

**Tech Stack:** PixiJS 6, pixi-live2d-display 0.4.0, Cubism Core SDK, Web Audio API (AnalyserNode)

---

## File Structure

### New Files
- `desktop/src/renderer/public/live2dcubismcore.min.js` — Cubism Core SDK (proprietary binary, loaded via script tag)
- `desktop/src/renderer/public/live2d/haru/` — Free demo model directory (Haru from CubismWebSamples)
- `desktop/src/renderer/lib/lip-sync.ts` — Audio amplitude analyzer for mouth parameter
- `desktop/src/renderer/components/Live2DAvatar.tsx` — Live2D model renderer
- `desktop/src/renderer/components/Live2DAvatar.module.css` — Canvas container styles
- `desktop/src/renderer/components/AvatarSwitch.tsx` — 2D/Live2D toggle wrapper
- `desktop/src/renderer/components/AvatarSwitch.module.css` — Toggle button styles

### Modified Files
- `desktop/src/renderer/index.html` — Add Cubism Core script tag
- `desktop/src/renderer/api.ts` — Extract `fetchTtsBlob()` from `speak()`
- `desktop/src/renderer/types.ts` — Add `CHARACTER_LIVE2D` mapping
- `desktop/src/renderer/App.tsx` — Replace `<Avatar>` with `<AvatarSwitch>`, handle audio flow for both modes
- `desktop/package.json` — New dependencies

---

### Task 1: Install Dependencies and Setup Cubism Core

**Files:**
- Modify: `desktop/package.json`
- Create: `desktop/src/renderer/public/live2dcubismcore.min.js`
- Modify: `desktop/src/renderer/index.html`

- [ ] **Step 1: Install npm packages**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npm install pixi.js@^6.5.10 pixi-live2d-display@^0.4.0
```

Expected: packages added to `dependencies` in package.json.

- [ ] **Step 2: Download Cubism Core SDK**

```bash
curl -L -o /Users/chao/Documents/Projects/nomi/desktop/src/renderer/public/live2dcubismcore.min.js \
  "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
```

Verify file is non-empty and contains `Live2DCubismCore`:
```bash
head -c 200 /Users/chao/Documents/Projects/nomi/desktop/src/renderer/public/live2dcubismcore.min.js
```

- [ ] **Step 3: Add Cubism Core script tag to index.html**

In `desktop/src/renderer/index.html`, add the script tag BEFORE the module script so `window.Live2DCubismCore` is available when pixi-live2d-display loads:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Nomi</title>
    <script src="/live2dcubismcore.min.js"></script>
  </head>
  <body style="margin: 0; padding: 0; background: transparent; overflow: hidden;">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Commit**

```bash
git add desktop/package.json desktop/package-lock.json desktop/src/renderer/public/live2dcubismcore.min.js desktop/src/renderer/index.html
git commit -m "feat(live2d): install pixi.js, pixi-live2d-display, and cubism core"
```

---

### Task 2: Download and Setup Haru Model

**Files:**
- Create: `desktop/src/renderer/public/live2d/haru/` (model files)

- [ ] **Step 1: Download Haru model from CubismWebSamples**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop/src/renderer/public
mkdir -p live2d/haru

# Clone the specific directory from CubismWebSamples
cd /tmp
git clone --depth 1 --filter=blob:none --sparse https://github.com/Live2D/CubismWebSamples.git
cd CubismWebSamples
git sparse-checkout set Samples/Resources/Haru

# Copy model files
cp -r Samples/Resources/Haru/* /Users/chao/Documents/Projects/nomi/desktop/src/renderer/public/live2d/haru/

# Cleanup
cd /Users/chao/Documents/Projects/nomi
rm -rf /tmp/CubismWebSamples
```

- [ ] **Step 2: Verify model file structure**

```bash
ls -la desktop/src/renderer/public/live2d/haru/
```

Expected files:
```
Haru.model3.json
Haru.moc3
Haru.physics3.json
Haru.pose3.json
Haru.cdi3.json
Haru.2048/
  texture_00.png
  texture_01.png
expressions/
  F01.exp3.json ... F08.exp3.json
motions/
  haru_g_idle.motion3.json
  ...
```

- [ ] **Step 3: Verify model3.json contains LipSync group**

```bash
cat desktop/src/renderer/public/live2d/haru/Haru.model3.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
groups = data.get('Groups', [])
lip = [g for g in groups if g.get('Name') == 'LipSync']
print('LipSync group:', lip)
exprs = data.get('FileReferences', {}).get('Expressions', [])
print('Expressions:', [e['Name'] for e in exprs])
motions = data.get('FileReferences', {}).get('Motions', {})
print('Motion groups:', list(motions.keys()))
"
```

Expected: LipSync group with `ParamMouthOpenY`, expressions list, motion groups including `Idle`.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/public/live2d/
git commit -m "feat(live2d): add Haru free demo model from CubismWebSamples"
```

---

### Task 3: Create LipSyncAnalyzer Utility

**Files:**
- Create: `desktop/src/renderer/lib/lip-sync.ts`

- [ ] **Step 1: Create lip-sync.ts**

```typescript
// desktop/src/renderer/lib/lip-sync.ts

/**
 * Analyzes audio amplitude in real-time for Live2D lip-sync.
 * Connects to an HTMLAudioElement via Web Audio API and provides
 * a smoothed amplitude value (0~1) for driving ParamMouthOpenY.
 */
export class LipSyncAnalyzer {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private dataArray: Uint8Array | null = null;
  private animFrameId: number = 0;
  private _amplitude: number = 0;
  private smoothing: number = 0.6; // higher = smoother, 0~1

  /**
   * Connect to an audio element and start analyzing.
   * Must be called after the audio element has started playing.
   */
  start(audioElement: HTMLAudioElement): void {
    this.stop();

    this.audioContext = new AudioContext();
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.3;

    this.source = this.audioContext.createMediaElementSource(audioElement);
    this.source.connect(this.analyser);
    this.analyser.connect(this.audioContext.destination); // still play through speakers

    const bufferLength = this.analyser.frequencyBinCount;
    this.dataArray = new Uint8Array(bufferLength);

    this.update();
  }

  private update = (): void => {
    if (!this.analyser || !this.dataArray) return;

    this.analyser.getByteFrequencyData(this.dataArray);

    // Calculate average amplitude from frequency data
    let sum = 0;
    for (let i = 0; i < this.dataArray.length; i++) {
      sum += this.dataArray[i];
    }
    const rawAmplitude = sum / (this.dataArray.length * 255); // normalize to 0~1

    // Apply exponential smoothing to avoid jittery mouth
    this._amplitude =
      this.smoothing * this._amplitude + (1 - this.smoothing) * rawAmplitude;

    this.animFrameId = requestAnimationFrame(this.update);
  };

  /** Get current smoothed amplitude (0~1) */
  getAmplitude(): number {
    return this._amplitude;
  }

  /** Disconnect and stop analyzing */
  stop(): void {
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = 0;
    }
    this._amplitude = 0;

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    this.dataArray = null;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/renderer/lib/lip-sync.ts
git commit -m "feat(live2d): add LipSyncAnalyzer utility for audio amplitude analysis"
```

---

### Task 4: Create Live2DAvatar Component

**Files:**
- Create: `desktop/src/renderer/components/Live2DAvatar.tsx`
- Create: `desktop/src/renderer/components/Live2DAvatar.module.css`

- [ ] **Step 1: Create Live2DAvatar.module.css**

```css
/* desktop/src/renderer/components/Live2DAvatar.module.css */

.container {
  position: relative;
  width: 400px;
  height: 400px;
  overflow: hidden;
}

.canvas {
  width: 100%;
  height: 100%;
}

/* Same status dot as Avatar.module.css */
.statusDot {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  z-index: 2;
  transition: background-color 0.3s;
}

.ready {
  background-color: #4ade80;
}

.dotThinking {
  background-color: #facc15;
  animation: pulse 1.2s infinite;
}

.dotSpeaking {
  background-color: #60a5fa;
  animation: pulse 0.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: translateX(-50%) scale(1); }
  50% { opacity: 0.5; transform: translateX(-50%) scale(1.3); }
}
```

- [ ] **Step 2: Create Live2DAvatar.tsx**

```typescript
// desktop/src/renderer/components/Live2DAvatar.tsx

import { useEffect, useRef, useCallback } from "react";
import * as PIXI from "pixi.js";
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { LipSyncAnalyzer } from "../lib/lip-sync";
import type { CharacterState } from "./Avatar";
import styles from "./Live2DAvatar.module.css";

// Register PIXI for pixi-live2d-display internal ticker
(window as any).PIXI = PIXI;

interface Live2DAvatarProps {
  modelPath: string;
  state: CharacterState;
  audioElement: HTMLAudioElement | null;
  width?: number;
  height?: number;
}

/**
 * Maps CharacterState to Haru model expressions.
 * Haru has expressions F01-F08. Adjust these names after
 * inspecting the actual model3.json Expressions array.
 */
const STATE_EXPRESSION_MAP: Record<CharacterState, string | null> = {
  idle: null,       // default expression
  listening: "F01",
  thinking: "F06",
  speaking: null,    // use default + lip-sync
  happy: "F02",
  sad: "F03",
  surprised: "F05",
};

/**
 * Maps CharacterState to motion groups.
 * null = don't trigger a motion (keep current).
 */
const STATE_MOTION_MAP: Record<CharacterState, string | null> = {
  idle: "Idle",
  listening: null,
  thinking: null,
  speaking: null,
  happy: "TapBody",
  sad: null,
  surprised: "TapBody",
};

export function Live2DAvatar({
  modelPath,
  state,
  audioElement,
  width = 400,
  height = 400,
}: Live2DAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<InstanceType<typeof Live2DModel> | null>(null);
  const lipSyncRef = useRef<LipSyncAnalyzer | null>(null);
  const lipSyncFrameRef = useRef<number>(0);

  // Initialize PixiJS app and load model
  useEffect(() => {
    if (!canvasRef.current) return;

    const app = new PIXI.Application({
      view: canvasRef.current,
      width,
      height,
      backgroundAlpha: 0, // transparent background
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });
    appRef.current = app;

    Live2DModel.from(modelPath).then((model) => {
      modelRef.current = model;

      // Scale model to fit canvas
      const scaleX = width / model.width;
      const scaleY = height / model.height;
      const scale = Math.min(scaleX, scaleY) * 0.8;
      model.scale.set(scale);

      // Center model
      model.x = width / 2 - (model.width * scale) / 2;
      model.y = height / 2 - (model.height * scale) / 2 + 20;

      app.stage.addChild(model);

      // Start idle motion
      model.motion("Idle", 0, 3); // priority 3 = idle
    }).catch((err) => {
      console.error("[Live2D] Failed to load model:", err);
    });

    return () => {
      // Cleanup
      if (lipSyncRef.current) {
        lipSyncRef.current.stop();
        lipSyncRef.current = null;
      }
      if (lipSyncFrameRef.current) {
        cancelAnimationFrame(lipSyncFrameRef.current);
      }
      modelRef.current = null;
      app.destroy(true);
      appRef.current = null;
    };
  }, [modelPath, width, height]);

  // Handle state changes → expressions and motions
  useEffect(() => {
    const model = modelRef.current;
    if (!model) return;

    const expression = STATE_EXPRESSION_MAP[state];
    if (expression) {
      model.expression(expression);
    }

    const motionGroup = STATE_MOTION_MAP[state];
    if (motionGroup) {
      // priority: Idle=1, Normal=2, Force=3
      const priority = motionGroup === "Idle" ? 1 : 2;
      model.motion(motionGroup, undefined, priority);
    }
  }, [state]);

  // Handle lip-sync: connect/disconnect when audioElement changes
  const startLipSync = useCallback((audio: HTMLAudioElement) => {
    const model = modelRef.current;
    if (!model) return;

    const analyzer = new LipSyncAnalyzer();
    lipSyncRef.current = analyzer;

    try {
      analyzer.start(audio);
    } catch (err) {
      console.error("[Live2D] LipSync start failed:", err);
      return;
    }

    // Drive mouth parameter on each frame
    const updateMouth = () => {
      if (!lipSyncRef.current || !modelRef.current) return;
      const amplitude = lipSyncRef.current.getAmplitude();
      try {
        const coreModel = (modelRef.current as any).internalModel.coreModel;
        coreModel.setParameterValueById("ParamMouthOpenY", amplitude * 1.4); // amplify slightly
      } catch {
        // Model may not be ready yet
      }
      lipSyncFrameRef.current = requestAnimationFrame(updateMouth);
    };
    updateMouth();
  }, []);

  const stopLipSync = useCallback(() => {
    if (lipSyncRef.current) {
      lipSyncRef.current.stop();
      lipSyncRef.current = null;
    }
    if (lipSyncFrameRef.current) {
      cancelAnimationFrame(lipSyncFrameRef.current);
      lipSyncFrameRef.current = 0;
    }
    // Reset mouth to closed
    try {
      const coreModel = (modelRef.current as any)?.internalModel?.coreModel;
      coreModel?.setParameterValueById("ParamMouthOpenY", 0);
    } catch {}
  }, []);

  useEffect(() => {
    if (audioElement) {
      startLipSync(audioElement);

      const handleEnded = () => stopLipSync();
      audioElement.addEventListener("ended", handleEnded);
      return () => {
        audioElement.removeEventListener("ended", handleEnded);
        stopLipSync();
      };
    } else {
      stopLipSync();
    }
  }, [audioElement, startLipSync, stopLipSync]);

  return (
    <div className={styles.container}>
      <canvas ref={canvasRef} className={styles.canvas} />
      <div
        className={`${styles.statusDot} ${
          state === "thinking"
            ? styles.dotThinking
            : state === "speaking"
            ? styles.dotSpeaking
            : styles.ready
        }`}
      />
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/Live2DAvatar.tsx desktop/src/renderer/components/Live2DAvatar.module.css
git commit -m "feat(live2d): add Live2DAvatar component with lip-sync support"
```

---

### Task 5: Modify api.ts — Extract fetchTtsBlob

**Files:**
- Modify: `desktop/src/renderer/api.ts:96-111`

- [ ] **Step 1: Add fetchTtsBlob and playAudioBlob methods**

Refactor `speak()` to extract the fetch logic. Also export `_playAudio` as `playAudioBlob` so App.tsx can play audio independently for Live2D mode.

Replace lines 34-111 in `api.ts` with:

```typescript
function _playAudio(blob: Blob): Promise<HTMLAudioElement> {
  const audioUrl = URL.createObjectURL(blob);
  const audio = new Audio(audioUrl);
  return new Promise((resolve, reject) => {
    audio.onloadedmetadata = () => {
      console.log(`[TTS] Audio duration: ${audio.duration}s`);
    };
    audio.onended = () => {
      console.log(`[TTS] Playback ended at ${audio.currentTime}s`);
      URL.revokeObjectURL(audioUrl);
      resolve(audio);
    };
    audio.onerror = (e) => {
      console.error(`[TTS] Audio error:`, e);
      URL.revokeObjectURL(audioUrl);
      reject(e);
    };
    audio.play().catch((e) => {
      console.error(`[TTS] Play failed:`, e);
      reject(e);
    });
  });
}
```

Then in the `api` object, replace the existing `speak` method and add `fetchTtsBlob` and `playAudioBlob`:

```typescript
  /** Fetch TTS audio as a blob without playing it */
  fetchTtsBlob: async (text: string, robotName: string, emotion: string = "Normal"): Promise<Blob | null> => {
    const character = ROBOT_VOICE_MAP[robotName] || "frieren";
    const url = `${BACKEND_URL}/api/tts/speak-genie?text=${encodeURIComponent(text)}&emotion=${encodeURIComponent(emotion)}&character=${encodeURIComponent(character)}&lang=auto`;
    console.log(`[TTS] Fetching: ${url.slice(0, 100)}...`);
    const res = await fetch(url);
    console.log(`[TTS] Response: ${res.status}, size=${res.headers.get("content-length")}`);
    if (!res.ok) throw new Error(`TTS error: ${res.status}`);
    const blob = await res.blob();
    console.log(`[TTS] Blob size: ${blob.size}`);
    if (blob.size < 1000) {
      console.warn("[TTS] Audio too small, skipping");
      return null;
    }
    return blob;
  },

  /** Play an audio blob, returns the HTMLAudioElement (resolves when playback ends) */
  playAudioBlob: (blob: Blob): Promise<HTMLAudioElement> => {
    return _playAudio(blob);
  },

  /** Speak text with a specific character's voice (fetch + play) */
  speak: async (text: string, robotName: string, emotion: string = "Normal"): Promise<void> => {
    const blob = await api.fetchTtsBlob(text, robotName, emotion);
    if (!blob) return;
    await _playAudio(blob);
  },
```

- [ ] **Step 2: Verify api.ts compiles**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npx tsc --noEmit --pretty 2>&1 | head -20
```

Expected: no errors in api.ts.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/api.ts
git commit -m "refactor(api): extract fetchTtsBlob and playAudioBlob from speak()"
```

---

### Task 6: Add Live2D Path Mapping to types.ts

**Files:**
- Modify: `desktop/src/renderer/types.ts`

- [ ] **Step 1: Add CHARACTER_LIVE2D mapping**

Add after the `ROBOT_TTS_LANG` block (after line 29):

```typescript
// Map robot names to Live2D model paths (relative to public/)
// Only robots with a Live2D model path can use Live2D display mode
export const CHARACTER_LIVE2D: Record<string, string> = {
  "フリーレン": "/live2d/haru/Haru.model3.json",
};
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/renderer/types.ts
git commit -m "feat(live2d): add CHARACTER_LIVE2D model path mapping"
```

---

### Task 7: Create AvatarSwitch Component

**Files:**
- Create: `desktop/src/renderer/components/AvatarSwitch.tsx`
- Create: `desktop/src/renderer/components/AvatarSwitch.module.css`

- [ ] **Step 1: Create AvatarSwitch.module.css**

```css
/* desktop/src/renderer/components/AvatarSwitch.module.css */

.wrapper {
  position: relative;
}

.toggleButton {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(8px);
  color: rgba(255, 255, 255, 0.7);
  font-size: 10px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.5px;
}

.toggleButton:hover {
  background: rgba(0, 0, 0, 0.5);
  color: white;
  border-color: rgba(255, 255, 255, 0.5);
}
```

- [ ] **Step 2: Create AvatarSwitch.tsx**

```typescript
// desktop/src/renderer/components/AvatarSwitch.tsx

import { useState, useCallback } from "react";
import { Avatar, type CharacterState } from "./Avatar";
import { Live2DAvatar } from "./Live2DAvatar";
import styles from "./AvatarSwitch.module.css";

type DisplayMode = "2d" | "live2d";

interface AvatarSwitchProps {
  characterDir: string;        // path to PNG assets (for 2D mode)
  live2dModelPath?: string;    // path to .model3.json (for Live2D mode)
  state: CharacterState;
  audioElement: HTMLAudioElement | null; // for Live2D lip-sync
  onClick: () => void;
  /** Unique key for persisting mode preference (e.g. robot name) */
  characterKey: string;
}

function getStoredMode(key: string): DisplayMode {
  try {
    const stored = localStorage.getItem(`nomi-display-mode-${key}`);
    if (stored === "live2d") return "live2d";
  } catch {}
  return "2d";
}

function storeMode(key: string, mode: DisplayMode): void {
  try {
    localStorage.setItem(`nomi-display-mode-${key}`, mode);
  } catch {}
}

export function AvatarSwitch({
  characterDir,
  live2dModelPath,
  state,
  audioElement,
  onClick,
  characterKey,
}: AvatarSwitchProps) {
  const [mode, setMode] = useState<DisplayMode>(() =>
    live2dModelPath ? getStoredMode(characterKey) : "2d"
  );

  const toggleMode = useCallback(() => {
    const next = mode === "2d" ? "live2d" : "2d";
    setMode(next);
    storeMode(characterKey, next);
  }, [mode, characterKey]);

  // If no Live2D model available, always render 2D
  const canLive2D = !!live2dModelPath;

  return (
    <div className={styles.wrapper} onClick={onClick}>
      {canLive2D && (
        <button
          className={styles.toggleButton}
          onClick={(e) => {
            e.stopPropagation(); // don't trigger avatar onClick
            toggleMode();
          }}
        >
          {mode === "2d" ? "3D" : "2D"}
        </button>
      )}

      {mode === "live2d" && live2dModelPath ? (
        <Live2DAvatar
          modelPath={live2dModelPath}
          state={state}
          audioElement={audioElement}
        />
      ) : (
        <Avatar
          characterDir={characterDir}
          state={state}
          onClick={() => {}} // onClick handled by wrapper
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/AvatarSwitch.tsx desktop/src/renderer/components/AvatarSwitch.module.css
git commit -m "feat(live2d): add AvatarSwitch component with 2D/3D toggle"
```

---

### Task 8: Integrate AvatarSwitch into App.tsx

**Files:**
- Modify: `desktop/src/renderer/App.tsx`

This is the most involved change. We need to:
1. Replace `<Avatar>` with `<AvatarSwitch>`
2. Track the current audio element for lip-sync
3. Use `fetchTtsBlob` + `playAudioBlob` when in Live2D mode to capture the audio element
4. Import the new types

- [ ] **Step 1: Update imports (line 1-9)**

Replace:
```typescript
import { Avatar, type CharacterState } from "./components/Avatar";
```

With:
```typescript
import type { CharacterState } from "./components/Avatar";
import { AvatarSwitch } from "./components/AvatarSwitch";
```

Add `CHARACTER_LIVE2D` to the types import:
```typescript
import { CHARACTER_DIRS, CHARACTER_LIVE2D, ROBOT_TTS_LANG } from "./types";
```

- [ ] **Step 2: Add audioElement state (after line 50)**

Add after `const [voiceEnabled, setVoiceEnabled] = useState(true);` (line 50):

```typescript
const [currentAudio, setCurrentAudio] = useState<HTMLAudioElement | null>(null);
```

- [ ] **Step 3: Create a shared TTS helper function**

Add a helper function inside the `App` component (after the `showSubtitle` function, around line 67) that handles TTS for both modes. This replaces the duplicated TTS logic in the reaction listener and handleSend:

```typescript
  /** Play TTS and track audio element for Live2D lip-sync */
  const playTts = useCallback(async (text: string, robotName: string, emotion: string) => {
    const blob = await api.fetchTtsBlob(text, robotName, emotion);
    if (!blob) return;

    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    setCurrentAudio(audio);

    return new Promise<void>((resolve, reject) => {
      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        setCurrentAudio(null);
        resolve();
      };
      audio.onerror = (e) => {
        URL.revokeObjectURL(audioUrl);
        setCurrentAudio(null);
        reject(e);
      };
      audio.play().catch((e) => {
        setCurrentAudio(null);
        reject(e);
      });
    });
  }, []);
```

- [ ] **Step 4: Update reaction listener TTS call (lines 147-150)**

Replace:
```typescript
      if (voiceEnabled && data.text_ja) {
        api.speak(data.text_ja, robot?.name || "", data.emotion || "Normal")
          .catch(console.error)
          .finally(() => setCharacterState("idle"));
      } else {
```

With:
```typescript
      if (voiceEnabled && data.text_ja) {
        playTts(data.text_ja, robot?.name || "", data.emotion || "Normal")
          .catch(console.error)
          .finally(() => setCharacterState("idle"));
      } else {
```

- [ ] **Step 5: Update handleSend TTS call (lines 260-266)**

Replace:
```typescript
          if (ttsText) {
            try {
              await api.speak(ttsText, robot.name, result.emotion || "Normal");
            } catch (e) {
              console.error("TTS failed:", e);
            }
          }
```

With:
```typescript
          if (ttsText) {
            try {
              await playTts(ttsText, robot.name, result.emotion || "Normal");
            } catch (e) {
              console.error("TTS failed:", e);
            }
          }
```

- [ ] **Step 6: Replace Avatar with AvatarSwitch (lines 346-352)**

Replace:
```typescript
          <Avatar
            characterDir={characterDir}
            state={characterState}
            onClick={() => setShowChat(!showChat)}
          />
```

With:
```typescript
          <AvatarSwitch
            characterDir={characterDir}
            live2dModelPath={robot ? CHARACTER_LIVE2D[robot.name] : undefined}
            state={characterState}
            audioElement={currentAudio}
            onClick={() => setShowChat(!showChat)}
            characterKey={robot?.name || "default"}
          />
```

- [ ] **Step 7: Verify build compiles**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: no type errors.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/renderer/App.tsx
git commit -m "feat(live2d): integrate AvatarSwitch with Live2D lip-sync in App.tsx"
```

---

### Task 9: Manual Verification

**Files:** None (testing only)

- [ ] **Step 1: Start dev server**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npm run dev
```

Expected: Vite dev server starts on localhost:5173, Electron window opens.

- [ ] **Step 2: Verify 2D mode works (regression)**

1. App should show frieren in 2D mode (PNG images) by default
2. Send a message — character should transition through thinking → speaking/emotion → idle
3. TTS audio should play normally
4. Confirm a small "3D" toggle button appears in the top-right corner of the avatar area

- [ ] **Step 3: Switch to Live2D mode**

1. Click the "3D" button in the avatar area
2. Haru Live2D model should appear on a transparent canvas
3. The model should play an idle breathing/swaying animation
4. The toggle button should now show "2D"

- [ ] **Step 4: Test Live2D state transitions**

1. Send a message — model should show thinking expression
2. When response arrives — model should show emotion expression (happy/sad/surprised)
3. TTS should play and Haru's mouth should move in sync with audio
4. After TTS ends — mouth closes, model returns to idle

- [ ] **Step 5: Test mode persistence**

1. Switch to Live2D mode, close and reopen the app
2. Frieren should load in Live2D mode (from localStorage)
3. Switch to a different character — they should be in 2D mode (no Live2D model)
4. Switch back to frieren — should still be in Live2D mode

- [ ] **Step 6: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix(live2d): address issues found during manual verification"
```

---

## Expression Mapping Notes

Haru's expressions (F01-F08) may not exactly match the mapping in `STATE_EXPRESSION_MAP`. After loading the model, inspect the console output or the model3.json to see actual expression names and adjust the mapping if needed. The current mapping is a best guess:

| CharacterState | Expression | Motion |
|---|---|---|
| idle | (default) | Idle (loop) |
| listening | F01 | — |
| thinking | F06 | — |
| speaking | (default) + lip-sync | — |
| happy | F02 | TapBody |
| sad | F03 | — |
| surprised | F05 | TapBody |
