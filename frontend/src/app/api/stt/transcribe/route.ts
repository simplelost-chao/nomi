import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function POST(req: NextRequest) {
  const formData = await req.formData();
  const res = await fetch(`${BACKEND_URL}/api/stt/transcribe`, {
    method: "POST",
    body: formData,
  });
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
