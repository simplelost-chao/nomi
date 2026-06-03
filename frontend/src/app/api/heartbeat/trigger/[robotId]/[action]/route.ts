import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ robotId: string; action: string }> }
) {
  const { robotId, action } = await params;
  const res = await fetch(
    `${BACKEND_URL}/api/heartbeat/trigger/${robotId}/${action}`,
    { method: "POST" }
  );
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
