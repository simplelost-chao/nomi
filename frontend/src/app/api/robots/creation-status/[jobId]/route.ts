import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  const res = await fetch(`${BACKEND_URL}/api/robots/creation-status/${jobId}`);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
