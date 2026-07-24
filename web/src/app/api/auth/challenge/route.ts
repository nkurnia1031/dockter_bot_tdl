import { NextResponse } from "next/server";
import { options } from "@/lib/bff";

const backend = process.env.BACKEND_API_URL || "http://backend:8080";

export async function POST() {
  const upstream = await fetch(`${backend}/api/v1/auth/telegram/challenges`, {method: "POST", cache: "no-store"});
  const data = await upstream.json();
  const response = NextResponse.json(data, {status: upstream.status});
  if (upstream.ok) {
    response.cookies.set("tme3_challenge", data.challenge_id, {...options, maxAge: 300});
    response.cookies.set("tme3_poll", data.poll_token, {...options, maxAge: 300});
  }
  return response;
}
