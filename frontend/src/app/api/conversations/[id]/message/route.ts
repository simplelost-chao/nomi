import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export const maxDuration = 120; // Allow up to 2 minutes for slow models

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const model = req.nextUrl.searchParams.get("model") || "deepseek-v4-flash";
  const robotId = req.nextUrl.searchParams.get("robot_id") || "";
  const body = await req.text();

  let url = `${BACKEND_URL}/api/conversations/${id}/message?model=${encodeURIComponent(model)}`;
  if (robotId) url += `&robot_id=${encodeURIComponent(robotId)}`;

  const res = await fetch(url,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(120000), // 2 min timeout
    }
  );

  const data = await res.text();
  return new Response(data, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
