// desktop/src/renderer/components/Live2DAvatar.tsx

import { useEffect, useRef, useCallback } from "react";
import * as PIXI from "pixi.js";
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { LipSyncAnalyzer } from "../lib/lip-sync";
import type { CharacterState } from "./Avatar";
import styles from "./Live2DAvatar.module.css";

// Module-level — bypasses React for per-frame updates
let _mouthValue = 0;
export function setMouthValue(v: number) { _mouthValue = v; }

let _modelScale = 1.15;
export function setModelScale(v: number) { _modelScale = v; }

let _followMouse = (() => {
  try { return localStorage.getItem("nomi-follow-mouse") === "true"; } catch { return false; }
})();
export function setFollowMouse(v: boolean) {
  _followMouse = v;
  try { localStorage.setItem("nomi-follow-mouse", String(v)); } catch {}
}
export function getFollowMouse() { return _followMouse; }

let _idleSway = (() => {
  try { return localStorage.getItem("nomi-idle-sway") !== "false"; } catch { return true; }
})();
export function setIdleSway(v: boolean) {
  _idleSway = v;
  try { localStorage.setItem("nomi-idle-sway", String(v)); } catch {}
}
export function getIdleSway() { return _idleSway; }

let _isSpeaking = false;
export function setIsSpeaking(v: boolean) { _isSpeaking = v; }

let _lastMouseX = 0;
let _lastMouseY = 0;
if (typeof window !== "undefined") {
  window.addEventListener("mousemove", (e) => {
    _lastMouseX = e.clientX;
    _lastMouseY = e.clientY;
  });
}

// Module-level audio element for lip-sync
let _activeAudio: HTMLAudioElement | null = null;
let _lipSyncAnalyzer: LipSyncAnalyzer | null = null;

export function startLipSync(audio: HTMLAudioElement) {
  stopLipSync();
  _activeAudio = audio;
  _isSpeaking = true;
  _lipSyncAnalyzer = new LipSyncAnalyzer();
  try {
    _lipSyncAnalyzer.start(audio);
  } catch (e) {
    console.error("[Live2D] LipSync start failed:", e);
    _lipSyncAnalyzer = null;
  }

  // Poll amplitude and drive mouth
  const update = () => {
    if (!_activeAudio) return;
    if (_activeAudio.paused || _activeAudio.ended) {
      _mouthValue = 0;
    } else if (_lipSyncAnalyzer) {
      _mouthValue = _lipSyncAnalyzer.getAmplitude() * 2.5;
    } else {
      // Fallback: sine wave while playing
      _mouthValue = (Math.sin(Date.now() / 120) + 1) / 2 * 0.8;
    }
    requestAnimationFrame(update);
  };
  update();

  audio.addEventListener("ended", stopLipSync);
}

export function stopLipSync() {
  _mouthValue = 0;
  _isSpeaking = false;
  if (_activeAudio) {
    _activeAudio.removeEventListener("ended", stopLipSync);
    _activeAudio = null;
  }
  if (_lipSyncAnalyzer) {
    _lipSyncAnalyzer.stop();
    _lipSyncAnalyzer = null;
  }
}

// Register PIXI for pixi-live2d-display internal ticker
(window as any).PIXI = PIXI;

interface Live2DAvatarProps {
  modelPath: string;
  state: CharacterState;
  modelScale?: number;
  width?: number;
  height?: number;
}

/**
 * Maps CharacterState to Haru model expressions.
 * Haru has expressions F01-F08. Adjust these names after
 * inspecting the actual model3.json Expressions array.
 */
// Frieren expressions: ku(苦/皱眉) yy(悠闲) han(汗/尴尬) mmy(眯眼/沉思)
// d(怒) lks(泪) wh(哇) zx(嘴角笑) anya(惊/可爱) anya2(笑眼)
// anyazZZ(困) W(瞪大眼) erd(委屈/嘟嘴) bl(?)
const STATE_EXPRESSION_MAP: Record<CharacterState, string | null> = {
  idle: null,          // natural resting face
  listening: "yy",     // calm/attentive
  thinking: "han",     // slight concentration (汗)
  speaking: "anya2",   // friendly talking (笑眼)
  happy: "zx",         // smile
  sad: "ku",           // pained/furrowed brows
  surprised: "W",      // wide eyes
};

const STATE_MOTION_MAP: Record<CharacterState, string | null> = {
  idle: null,
  listening: null,
  thinking: null,
  speaking: null,
  happy: null,
  sad: null,
  surprised: null,
};

export function Live2DAvatar({
  modelPath,
  state,
  modelScale = 1.15,
  width = 400,
  height = 400,
}: Live2DAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<InstanceType<typeof Live2DModel> | null>(null);

  // Create app + load model in a single effect
  useEffect(() => {
    if (!canvasRef.current) return;

    // Create app if needed
    if (!appRef.current) {
      appRef.current = new PIXI.Application({
        view: canvasRef.current,
        width,
        height,
        backgroundAlpha: 0,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
      });
    }
    const app = appRef.current;

    // Remove old model
    if (modelRef.current) {
      app.stage.removeChild(modelRef.current);
      modelRef.current.destroy();
      modelRef.current = null;
    }

    let cancelled = false;
    Live2DModel.from(modelPath).then((model) => {
      if (cancelled) { model.destroy(); return; }

      modelRef.current = model;

      const baseScaleX = width / model.width;
      const baseScaleY = height / model.height;
      const baseScale = Math.min(baseScaleX, baseScaleY);
      _modelScale = modelScale;
      model.scale.set(baseScale * _modelScale);

      model.anchor.set(0.5, 0.5);
      model.x = width / 2;
      model.y = height / 2;

      app.stage.addChild(model);

      // Let library handle idle animation naturally
      (model as any).autoInteract = _followMouse;

      // Patch internalModel.update: lip-sync + live scale
      const im = (model as any).internalModel;
      const mouthParamIndex = im.coreModel.getParameterIndex("ParamMouthOpenY");

      // Get head/eye parameter indices for manual override after physics
      const paramAngleXIdx = im.coreModel.getParameterIndex("ParamAngleX");
      const paramAngleYIdx = im.coreModel.getParameterIndex("ParamAngleY");
      const paramBodyAngleXIdx = im.coreModel.getParameterIndex("ParamBodyAngleX");
      const paramEyeBallXIdx = im.coreModel.getParameterIndex("ParamEyeBallX");
      const paramEyeBallYIdx = im.coreModel.getParameterIndex("ParamEyeBallY");

      const originalUpdate = im.update.bind(im);
      im.update = (dt: number, now: number) => {
        model.scale.set(baseScale * _modelScale);
        (model as any).autoInteract = _followMouse;

        // Set focus BEFORE update (for the model's internal focus controller)
        if (_followMouse) {
          const rect = canvasRef.current?.getBoundingClientRect();
          if (rect) {
            (model as any).focus(_lastMouseX - rect.left, _lastMouseY - rect.top);
          }
        } else {
          (model as any).focus(width / 2, height * 0.495);
        }

        originalUpdate(dt, now);


        // Lip-sync
        if (mouthParamIndex >= 0 && _mouthValue > 0) {
          im.coreModel.setParameterValueByIndex(mouthParamIndex, _mouthValue);
          im.coreModel.update();
        }
      };
    }).catch((err) => {
      console.error("[Live2D] Failed to load model:", err);
    });

    return () => {
      cancelled = true;
      stopLipSync();
      if (modelRef.current && app.stage) {
        app.stage.removeChild(modelRef.current);
        modelRef.current.destroy();
        modelRef.current = null;
      }
    };
  }, [modelPath]);


  // Handle state changes → expressions and motions
  useEffect(() => {
    const model = modelRef.current;
    if (!model) return;

    const expression = STATE_EXPRESSION_MAP[state];
    if (expression) {
      model.expression(expression);
    } else {
      // Force reset: set expression index 0 (neutral) to clear any active expression
      try {
        model.expression(0);
      } catch {}
      // Also force eyes open via the update patch
      try {
        const cm = (model as any).internalModel.coreModel;
        const eyeL = cm.getParameterIndex("ParamEyeLOpen");
        const eyeR = cm.getParameterIndex("ParamEyeROpen");
        const eyeLSmile = cm.getParameterIndex("ParamEyeLSmile");
        const eyeRSmile = cm.getParameterIndex("ParamEyeRSmile");
        if (eyeL >= 0) cm.setParameterValueByIndex(eyeL, 1);
        if (eyeR >= 0) cm.setParameterValueByIndex(eyeR, 1);
        if (eyeLSmile >= 0) cm.setParameterValueByIndex(eyeLSmile, 0);
        if (eyeRSmile >= 0) cm.setParameterValueByIndex(eyeRSmile, 0);
      } catch {}
    }

    const motionGroup = STATE_MOTION_MAP[state];
    if (motionGroup) {
      // priority: Idle=1, Normal=2, Force=3
      const priority = motionGroup === "Idle" ? 1 : 2;
      model.motion(motionGroup, undefined, priority);
    }
  }, [state]);

  // Lip-sync is handled via module-level startLipSync/stopLipSync (bypasses React)

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
