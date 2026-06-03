# Live2D Integration Design — Frieren Demo

**Date:** 2026-05-30
**Status:** Draft
**Scope:** Desktop app — add Live2D character rendering as alternative to existing 2D PNG avatars

## Goal

Add Live2D support to the desktop companion app with a 2D/Live2D toggle, using a free demo model (Haru) to validate the technical pipeline: PixiJS rendering in Electron transparent window + TTS lip-sync.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Model source | Cubism SDK free sample (Haru) | Validate tech pipeline first, custom models later |
| 2D/3D coexistence | Toggle button on avatar area | Both modes preserved, per-character localStorage |
| Interaction level | State animations + lip-sync only | Match 2D feature parity; mouse tracking/click later |
| Window layout | Unchanged (680×520) | Minimize scope; adjust later if needed |

## Architecture

### New Components

**`AvatarSwitch.tsx`** — Wrapper that manages display mode and renders either `Avatar` or `Live2DAvatar`.

```typescript
interface AvatarSwitchProps {
  characterDir: string;           // path to PNG assets (2D mode)
  live2dModelPath?: string;       // path to .model3.json (Live2D mode)
  state: CharacterState;          // "idle" | "speaking" | "thinking" | ...
  audioElement?: HTMLAudioElement; // for lip-sync when speaking
}
```

- Reads/writes `displayMode` to `localStorage` keyed by character name
- Renders a small toggle button (2D ↔ 3D) in the avatar area
- If no `live2dModelPath` provided, forces 2D mode (graceful fallback)

**`Live2DAvatar.tsx`** — Renders Live2D model on a PixiJS canvas.

```typescript
interface Live2DAvatarProps {
  modelPath: string;              // "/live2d/haru/haru.model3.json"
  state: CharacterState;
  audioElement?: HTMLAudioElement;
  width?: number;                 // default 400
  height?: number;                // default 400
}
```

- Creates a PixiJS `Application` with transparent background
- Loads model via `pixi-live2d-display`
- Maps `CharacterState` to model motions/expressions:
  - `idle` → idle motion (loop)
  - `thinking` → thinking expression
  - `speaking` → speaking motion + lip-sync enabled
  - `listening` → listening expression
  - `happy` → happy expression
  - `sad` → sad expression
  - `surprised` → surprised expression
- Starts/stops `LipSyncAnalyzer` when `state` transitions to/from `speaking`

**`lib/lip-sync.ts`** — Audio analysis utility.

```typescript
class LipSyncAnalyzer {
  constructor(audioElement: HTMLAudioElement)
  start(): void           // connect AudioContext + AnalyserNode + rAF loop
  stop(): void            // disconnect + stop loop
  getAmplitude(): number  // 0~1, smoothed volume level
}
```

- Uses `AudioContext` → `MediaElementSource` → `AnalyserNode`
- `getByteFrequencyData()` → average amplitude → smoothed with exponential decay
- Drives `ParamMouthOpenY` parameter on the Live2D model (0~1)

### Modified Files

**`api.ts`** — `speak()` method change:
- Currently creates `Audio()` internally and plays it
- Change: return the `HTMLAudioElement` so the caller (App.tsx) can pass it to `AvatarSwitch` for lip-sync
- Both 2D and Live2D modes still hear the audio; Live2D mode additionally analyzes it

**`App.tsx`** — Minimal changes:
- Replace `<Avatar>` with `<AvatarSwitch>`
- Store `audioElement` in state when `speak()` returns it
- Pass `audioElement` to `AvatarSwitch`

**`types.ts`** — Add Live2D model path mapping:

```typescript
export const CHARACTER_LIVE2D: Record<string, string> = {
  "フリーレン": "/live2d/haru/haru.model3.json",
};
```

### File Structure (new files)

```
desktop/src/renderer/
  ├── components/
  │   ├── AvatarSwitch.tsx          ← mode toggle wrapper
  │   ├── AvatarSwitch.module.css   ← toggle button styles
  │   ├── Live2DAvatar.tsx          ← Live2D renderer
  │   └── Live2DAvatar.module.css   ← canvas styling
  ├── lib/
  │   └── lip-sync.ts              ← audio analysis
  └── public/
      └── live2d/
          └── haru/                 ← free demo model files
              ├── haru.model3.json
              ├── haru.moc3
              ├── haru.8192/
              │   └── texture_00.png
              └── motions/
                  └── *.motion3.json
```

### Dependencies (new npm packages)

- `pixi.js` — 2D WebGL renderer
- `pixi-live2d-display` — Live2D integration for PixiJS
- Cubism SDK core (bundled via pixi-live2d-display or loaded separately)

## Data Flow

```
User input → App.tsx sets characterState="thinking"
                │
                ▼
          AvatarSwitch
           ├── 2D:     Avatar.tsx swaps PNG (unchanged)
           └── Live2D:  Live2DAvatar plays "thinking" expression
                │
Agent responds → characterState="speaking" + TTS starts
                │
                ▼
          api.speak() returns HTMLAudioElement
                │
                ├── Audio plays through speakers (both modes)
                │
                └── Live2D mode: LipSyncAnalyzer
                      AudioContext → AnalyserNode → amplitude
                      rAF loop → model.setParameterValueById("ParamMouthOpenY", amp)
                │
TTS ends → characterState="idle"
```

## Scope Boundaries

**In scope (this demo):**
- PixiJS + pixi-live2d-display rendering in Electron transparent window
- Free Haru model with state-based motion/expression
- TTS lip-sync via Web Audio API amplitude analysis
- 2D/Live2D toggle button with localStorage persistence
- Existing 2D mode completely unchanged

**Out of scope (future):**
- Custom Live2D models for each character
- Mouse/eye tracking
- Click interaction (touch reactions)
- Window resize for Live2D mode
- Live2D in web frontend
- Model quality/aesthetic matching with character art style

## Risks

- **Transparent canvas in Electron**: PixiJS canvas with `backgroundAlpha: 0` should work but needs testing with Electron's transparent window
- **Cubism SDK licensing**: Free for indie/small projects; the official sample models are freely distributable for development
- **pixi-live2d-display compatibility**: Need to verify compatibility with latest pixi.js v7/v8 — may need to pin versions
