import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function GET(req: NextRequest) {
  const text = req.nextUrl.searchParams.get("text") || "";
  const robotName = req.nextUrl.searchParams.get("robot_name") || "";
  const robotId = req.nextUrl.searchParams.get("robot_id") || "";
  const rangeHeader = req.headers.get("range");

  const textPreview = decodeURIComponent(text).slice(0, 30);
  console.log(`[TTS] ▶ request: robot=${robotName} text="${textPreview}..." range=${rangeHeader || "none"}`);

  const params = req.nextUrl.searchParams.toString();
  const backendUrl = `${BACKEND_URL}/api/tts/speak?${params}`;
  console.log(`[TTS]   fetching: ${BACKEND_URL}/api/tts/speak?text=${textPreview}...&robot_id=${robotId}`);

  const res = await fetch(backendUrl, {
    signal: AbortSignal.timeout(30_000),
    cache: "no-store",
  });

  console.log(`[TTS]   backend responded: status=${res.status} content-type=${res.headers.get("Content-Type")}`);

  if (!res.ok) {
    console.log(`[TTS]   ✗ backend error: ${res.status}`);
    return new Response("TTS error", { status: res.status });
  }

  const audioBuffer = await res.arrayBuffer();
  const total = audioBuffer.byteLength;
  const contentType = res.headers.get("Content-Type") || "audio/wav";

  console.log(`[TTS]   ✓ got ${total} bytes of ${contentType} for "${textPreview}..."`);

  if (rangeHeader) {
    const match = rangeHeader.match(/bytes=(\d*)-(\d*)/);
    const start = match?.[1] ? parseInt(match[1]) : 0;
    const end = match?.[2] ? parseInt(match[2]) : total - 1;
    const chunkEnd = Math.min(end, total - 1);
    const chunk = audioBuffer.slice(start, chunkEnd + 1);
    console.log(`[TTS]   returning 206 range ${start}-${chunkEnd}/${total}`);

    return new Response(chunk, {
      status: 206,
      headers: {
        "Content-Type": contentType,
        "Content-Range": `bytes ${start}-${chunkEnd}/${total}`,
        "Content-Length": String(chunk.byteLength),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
      },
    });
  }

  console.log(`[TTS]   returning 200 full ${total} bytes`);
  return new Response(audioBuffer, {
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(total),
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store, no-cache, must-revalidate",
      "Pragma": "no-cache",
    },
  });
}
