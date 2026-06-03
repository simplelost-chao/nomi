import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8100";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${BACKEND_URL}/api/robots/${id}`);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${BACKEND_URL}/api/robots/${id}`, { method: "DELETE" });
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
