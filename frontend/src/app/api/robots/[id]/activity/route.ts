import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { searchParams } = new URL(req.url);
  const qs = searchParams.toString();
  const res = await fetch(`${BACKEND_URL}/api/robots/${id}/activity${qs ? `?${qs}` : ""}`);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
