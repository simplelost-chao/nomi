import { useEffect, useState } from "react";
import type { Robot } from "../types";
import { setModelScale, setFollowMouse, getFollowMouse, setIdleSway, getIdleSway } from "./Live2DAvatar";

const BACKEND_URL = "http://127.0.0.1:8100";

interface AgentConfig {
  screenSensor: { enabled: boolean; intervalSec: number };
  clipboardSensor: { enabled: boolean };
  appSensor: { enabled: boolean };
  webSearch: { enabled: boolean };
  notification: { enabled: boolean };
  fileAccess: { enabled: boolean };
  openUrl: { enabled: boolean };
  voice: { enabled: boolean };
  minReactionIntervalSec: number;
  ollamaModel: string;
  ollamaUrl: string;
}

interface Props {
  onClose: () => void;
  robot?: Robot | null;
  heartbeatInterval?: number;
  onHeartbeatIntervalChange?: (sec: number) => void;
}

export function AgentSettings({ onClose, robot, heartbeatInterval = 10, onHeartbeatIntervalChange }: Props) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [live2dScale, setLive2dScale] = useState<number>((robot?.voice_profile as any)?.live2d_scale ?? 1.15);
  const [followMouse, setFollowMouseState] = useState(getFollowMouse);
  const [idleSway, setIdleSwayState] = useState(getIdleSway);

  useEffect(() => {
    window.nomi.agent.getConfig().then((c) => setConfig(c as unknown as AgentConfig));
  }, []);

  async function toggle(path: string, value: boolean) {
    if (!config) return;
    const parts = path.split(".");
    let update: Record<string, unknown> = {};
    if (parts.length === 2) {
      update = { [parts[0]]: { ...(config as any)[parts[0]], [parts[1]]: value } };
    } else {
      update = { [parts[0]]: value };
    }
    const newConfig = await window.nomi.agent.updateConfig(update);
    setConfig(newConfig as unknown as AgentConfig);
  }

  async function setInterval(sec: number) {
    if (!config) return;
    const newConfig = await window.nomi.agent.updateConfig({
      screenSensor: { ...config.screenSensor, intervalSec: sec },
    });
    setConfig(newConfig as unknown as AgentConfig);
  }

  async function setMinInterval(sec: number) {
    const newConfig = await window.nomi.agent.updateConfig({ minReactionIntervalSec: sec });
    setConfig(newConfig as unknown as AgentConfig);
  }

  if (!config) return null;

  const Toggle = ({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) => (
    <label className="flex items-center justify-between py-1.5">
      <span className="text-[13px] text-gray-700">{label}</span>
      <div
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full cursor-pointer transition-colors ${checked ? "bg-purple-400" : "bg-gray-300"}`}
      >
        <div className={`w-4 h-4 mt-0.5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4.5" : "translate-x-0.5"}`} />
      </div>
    </label>
  );

  return (
    <div className="absolute inset-0 z-50 bg-black/20 flex items-start justify-end pt-10 pr-4" onClick={onClose}>
      <div className="bg-white/90 backdrop-blur-lg rounded-2xl shadow-xl border border-white/50 w-[260px] max-h-[460px] overflow-y-auto p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[15px] font-bold text-gray-800">Agent 设置</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">x</button>
        </div>

        <p className="text-[11px] text-gray-400 mb-2">感知功能</p>
        <Toggle label="👁 屏幕感知" checked={config.screenSensor.enabled} onChange={(v) => toggle("screenSensor.enabled", v)} />
        {config.screenSensor.enabled && (
          <div className="ml-6 mb-1">
            <span className="text-[11px] text-gray-400 mr-2">频率</span>
            <select
              value={config.screenSensor.intervalSec}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="text-[12px] bg-gray-100 rounded px-1.5 py-0.5"
            >
              {[10, 30, 60, 120].map((s) => <option key={s} value={s}>{s}s</option>)}
            </select>
          </div>
        )}
        <Toggle label="📋 剪贴板感知" checked={config.clipboardSensor.enabled} onChange={(v) => toggle("clipboardSensor.enabled", v)} />
        <Toggle label="📱 应用切换感知" checked={config.appSensor.enabled} onChange={(v) => toggle("appSensor.enabled", v)} />

        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">动作功能</p>
        <Toggle label="🔍 网页搜索" checked={config.webSearch.enabled} onChange={(v) => toggle("webSearch.enabled", v)} />
        <Toggle label="🔔 系统通知" checked={config.notification.enabled} onChange={(v) => toggle("notification.enabled", v)} />
        <Toggle label="📂 文件访问" checked={config.fileAccess.enabled} onChange={(v) => toggle("fileAccess.enabled", v)} />
        <Toggle label="🌐 打开网页/应用" checked={config.openUrl.enabled} onChange={(v) => toggle("openUrl.enabled", v)} />

        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">输出</p>
        <Toggle label="🔊 语音播放" checked={config.voice.enabled} onChange={(v) => toggle("voice.enabled", v)} />

        {robot && (
          <>
            <div className="border-t border-gray-100 my-3" />
            <p className="text-[11px] text-gray-400 mb-2">Live2D</p>
            <label className="flex items-center justify-between py-1.5">
              <span className="text-[13px] text-gray-700">模型缩放</span>
              <span className="text-[12px] text-purple-500 font-medium w-8 text-right">{live2dScale.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min="0.5"
              max="2.0"
              step="0.05"
              value={live2dScale}
              className="w-full h-1 accent-purple-400 mb-2"
              onChange={(e) => {
                const val = parseFloat(e.target.value);
                setLive2dScale(val);
                setModelScale(val); // Direct update, no React re-render
              }}
              onMouseUp={async () => {
                if (!robot) return;
                const vp = { ...(robot.voice_profile || {}), live2d_scale: live2dScale };
                try {
                  await fetch(`${BACKEND_URL}/api/robots/${robot.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ voice_profile: vp }),
                  });
                } catch (e) {
                  console.error("Save scale failed:", e);
                }
              }}
            />
            <Toggle
              label="👀 跟随鼠标"
              checked={followMouse}
              onChange={(v) => {
                setFollowMouseState(v);
                setFollowMouse(v);
              }}
            />
          </>
        )}
        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">心跳</p>
        <label className="flex items-center justify-between py-1.5">
          <span className="text-[13px] text-gray-700">❤️ 心跳间隔</span>
          <select
            value={heartbeatInterval}
            onChange={(e) => {
              const v = Number(e.target.value);
              onHeartbeatIntervalChange?.(v);
              try { localStorage.setItem("nomi-heartbeat-interval", String(v)); } catch {}
            }}
            className="text-[12px] bg-gray-100 rounded px-1.5 py-0.5"
          >
            {[5, 10, 15, 30, 60].map((s) => <option key={s} value={s}>{s}s</option>)}
          </select>
        </label>

        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">其他</p>
        <label className="flex items-center justify-between py-1.5">
          <span className="text-[13px] text-gray-700">💬 最小打扰间隔</span>
          <select
            value={config.minReactionIntervalSec}
            onChange={(e) => setMinInterval(Number(e.target.value))}
            className="text-[12px] bg-gray-100 rounded px-1.5 py-0.5"
          >
            {[30, 60, 120, 300, 600].map((s) => <option key={s} value={s}>{s >= 60 ? `${s / 60}min` : `${s}s`}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
