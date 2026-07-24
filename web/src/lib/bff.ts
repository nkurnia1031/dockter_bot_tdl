import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies, headers } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const backend = process.env.BACKEND_API_URL || "http://backend:8080";
const cookieSecret = process.env.WEB_COOKIE_SECRET || process.env.AUTH_JWT_SECRET || "";
const secure = process.env.NODE_ENV === "production";
const options = {httpOnly: true, secure, sameSite: "lax" as const, path: "/ui"};

export async function backendFetch(path: string, init: RequestInit = {}, retry = true) {
  const jar = await cookies();
  const requestHeaders = new Headers(init.headers);
  const access = jar.get("tme3_access")?.value;
  const profile = readProfile(jar.get("tme3_profile")?.value);
  if (access) requestHeaders.set("Authorization", `Bearer ${access}`);
  if (profile) requestHeaders.set("X-Profile", profile);
  let response = await fetch(`${backend}${path}`, {...init, headers: requestHeaders, cache: "no-store"});
  if (response.status === 401 && retry && jar.get("tme3_refresh")?.value) {
    const refreshed = await fetch(`${backend}/api/v1/auth/refresh`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({refresh_token: jar.get("tme3_refresh")!.value}),
      cache: "no-store",
    });
    if (refreshed.ok) {
      const pair = await refreshed.json();
      jar.set("tme3_access", pair.access_token, {...options, maxAge: pair.expires_in});
      jar.set("tme3_refresh", pair.refresh_token, {...options, maxAge: 30 * 86400});
      requestHeaders.set("Authorization", `Bearer ${pair.access_token}`);
      response = await fetch(`${backend}${path}`, {...init, headers: requestHeaders, cache: "no-store"});
    }
  }
  return response;
}

export async function validateMutation(request: NextRequest) {
  const host = (await headers()).get("host");
  const origin = request.headers.get("origin");
  if (origin && new URL(origin).host !== host) return false;
  const jar = await cookies();
  const cookie = jar.get("tme3_csrf")?.value || "";
  const header = request.headers.get("x-csrf-token") || "";
  return Boolean(cookie && header && cookie === header);
}

export function copyResponse(source: Response) {
  return new NextResponse(source.body, {
    status: source.status,
    headers: {"Content-Type": source.headers.get("content-type") || "application/json"},
  });
}

export function sessionCookies(response: NextResponse, pair: Record<string, string | number>) {
  response.cookies.set("tme3_access", String(pair.access_token), {...options, maxAge: Number(pair.expires_in)});
  response.cookies.set("tme3_refresh", String(pair.refresh_token), {...options, maxAge: 30 * 86400});
  response.cookies.set("tme3_csrf", randomBytes(24).toString("base64url"), {...options, httpOnly: false});
}

export function clearSession(response: NextResponse) {
  for (const name of ["tme3_access", "tme3_refresh", "tme3_profile", "tme3_csrf", "tme3_challenge", "tme3_poll"]) {
    response.cookies.set(name, "", {...options, maxAge: 0});
  }
}

export function signProfile(profile: string) {
  if (!cookieSecret) throw new Error("WEB_COOKIE_SECRET belum dikonfigurasi.");
  const value = Buffer.from(profile).toString("base64url");
  const signature = createHmac("sha256", cookieSecret).update(`profile:${value}`).digest("base64url");
  return `${value}.${signature}`;
}

export function readProfile(signed?: string) {
  if (!signed || !cookieSecret) return undefined;
  const [value, signature] = signed.split(".");
  if (!value || !signature) return undefined;
  const expected = createHmac("sha256", cookieSecret).update(`profile:${value}`).digest("base64url");
  const left = Buffer.from(signature);
  const right = Buffer.from(expected);
  if (left.length !== right.length || !timingSafeEqual(left, right)) return undefined;
  return Buffer.from(value, "base64url").toString();
}

export {options};
