import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export const maxDuration = 120;

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; module: string }> }
) {
  const { id, module } = await params;
  const model = req.nextUrl.searchParams.get("model") || "deepseek-v4-flash";

  const res = await fetch(
    `${BACKEND_URL}/api/robots/${id}/regenerate/${module}?model=${encodeURIComponent(model)}`,
    { method: "POST", signal: AbortSignal.timeout(120000) }
  );

  const data = await res.json();
  return Response.json(data, { status: res.status });
}
