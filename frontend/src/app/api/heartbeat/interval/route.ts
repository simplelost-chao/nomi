import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function POST(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const seconds = searchParams.get("seconds") ?? "5";
  const res = await fetch(`${BACKEND_URL}/api/heartbeat/interval?seconds=${seconds}`, {
    method: "POST",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
