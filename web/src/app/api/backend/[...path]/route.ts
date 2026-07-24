import { NextRequest } from "next/server";
import { backendFetch, copyResponse, validateMutation } from "@/lib/bff";

async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  if (!["GET", "HEAD"].includes(request.method) && !(await validateMutation(request))) {
    return Response.json({error: {code: "CSRF_FAILED", message: "Request mutation ditolak."}}, {status: 403});
  }
  const {path} = await context.params;
  const target = `/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
  return copyResponse(await backendFetch(target, {method: request.method, headers, body}));
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
