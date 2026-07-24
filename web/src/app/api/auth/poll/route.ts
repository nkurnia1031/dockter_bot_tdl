import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { options, sessionCookies } from "@/lib/bff";

const backend = process.env.BACKEND_API_URL || "http://backend:8080";

export async function POST() {
  const jar = await cookies();
  const challenge = jar.get("tme3_challenge")?.value;
  const poll = jar.get("tme3_poll")?.value;
  if (!challenge || !poll) return NextResponse.json({error: {code: "CHALLENGE_COOKIE_REQUIRED", message: "Mulai login lagi."}}, {status: 401});
  const upstream = await fetch(`${backend}/api/v1/auth/telegram/challenges/${challenge}/token`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({poll_token: poll}), cache: "no-store",
  });
  const data = await upstream.json();
  const response = NextResponse.json(data, {status: upstream.status});
  if (upstream.ok && data.access_token) {
    sessionCookies(response, data);
    response.cookies.set("tme3_challenge", "", {...options, maxAge: 0});
    response.cookies.set("tme3_poll", "", {...options, maxAge: 0});
  }
  return response;
}
