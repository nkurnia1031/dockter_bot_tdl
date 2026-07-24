import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { clearSession, validateMutation } from "@/lib/bff";

const backend = process.env.BACKEND_API_URL || "http://backend:8080";

export async function POST(request: NextRequest) {
  if (!(await validateMutation(request))) return NextResponse.json({error: "CSRF"}, {status: 403});
  const jar = await cookies();
  const refresh = jar.get("tme3_refresh")?.value;
  if (refresh) await fetch(`${backend}/api/v1/auth/logout`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({refresh_token: refresh}), cache: "no-store",
  });
  const response = NextResponse.json({revoked: true});
  clearSession(response);
  return response;
}
