import { AgentConfig } from "./agent-config";

export interface AnalysisResult {
  scene: string;
  interesting: boolean;
  reason: string;
}

const recentScenes: string[] = [];
const MAX_RECENT = 5;

export async function analyzeScreen(
  imageBase64: string,
  appName: string,
  windowTitle: string,
  clipboardText: string | null,
  config: AgentConfig
): Promise<AnalysisResult | null> {
  const lastScene = recentScenes.length > 0 ? recentScenes[recentScenes.length - 1] : "无";

  const prompt = `你是一个桌面观察者。根据截图和上下文，简要描述用户在做什么，判断是否值得评论。

当前应用: ${appName}
窗口标题: ${windowTitle}
${clipboardText ? `剪贴板: ${clipboardText}` : ""}
上次场景: ${lastScene}

输出严格的JSON格式（不要包含其他文字）:
{"scene": "用户在做什么的简要描述", "interesting": true或false, "reason": "为什么值得或不值得评论"}

规则:
- 跟上次一样的场景 → interesting: false
- 用户切换了应用或在做新事情 → interesting: true
- 看到有趣的内容（视频、游戏、新闻、社交）→ interesting: true
- 纯打字没变化 → interesting: false`;

  try {
    const response = await fetch(`${config.ollamaUrl}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: config.ollamaModel,
        prompt,
        images: [imageBase64],
        stream: false,
        options: { temperature: 0.3, num_predict: 200 },
      }),
    });

    if (!response.ok) {
      console.error("[analyzer] Ollama error:", response.status);
      return null;
    }

    const data = await response.json();
    const text = data.response || "";

    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      console.warn("[analyzer] No JSON in response:", text.slice(0, 100));
      return null;
    }

    const result: AnalysisResult = JSON.parse(jsonMatch[0]);

    if (result.interesting) {
      const isDuplicate = recentScenes.some(
        (s) => s === result.scene || levenshteinSimilarity(s, result.scene) > 0.7
      );
      if (isDuplicate) {
        result.interesting = false;
        result.reason = "与最近的场景重复";
      }
    }

    recentScenes.push(result.scene);
    if (recentScenes.length > MAX_RECENT) recentScenes.shift();

    return result;
  } catch (err) {
    console.error("[analyzer] Failed:", err);
    return null;
  }
}

function levenshteinSimilarity(a: string, b: string): number {
  if (a === b) return 1;
  const longer = a.length > b.length ? a : b;
  const shorter = a.length > b.length ? b : a;
  if (longer.length === 0) return 1;
  let matches = 0;
  for (const ch of shorter) {
    if (longer.includes(ch)) matches++;
  }
  return matches / longer.length;
}

export async function checkOllamaHealth(url: string): Promise<boolean> {
  try {
    const res = await fetch(`${url}/api/tags`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

export function resetAnalyzerHistory(): void {
  recentScenes.length = 0;
}
