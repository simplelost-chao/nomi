import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ robotId: string }> }
) {
  const { robotId } = await params;
  const res = await fetch(`${BACKEND_URL}/api/tts/regenerate/${robotId}`, { method: "POST" });
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
