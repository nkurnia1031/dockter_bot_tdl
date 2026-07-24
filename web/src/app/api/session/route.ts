import { NextRequest, NextResponse } from "next/server";
import { backendFetch, copyResponse, options, signProfile, validateMutation } from "@/lib/bff";

export async function GET() {
  const [me, profiles] = await Promise.all([
    backendFetch("/api/v1/me"),
    backendFetch("/api/v1/profiles"),
  ]);
  if (!me.ok) return copyResponse(me);
  return NextResponse.json({actor: await me.json(), profiles: profiles.ok ? (await profiles.json()).items : []});
}

export async function PUT(request: NextRequest) {
  if (!(await validateMutation(request))) return NextResponse.json({error: "CSRF"}, {status: 403});
  const {profile} = await request.json();
  const profiles = await backendFetch("/api/v1/profiles");
  if (!profiles.ok) return copyResponse(profiles);
  const allowed = (await profiles.json()).items.some((item: {name: string}) => item.name === profile);
  if (!allowed) return NextResponse.json({error: {code: "PROFILE_NOT_FOUND", message: "Profile tidak ditemukan."}}, {status: 404});
  const response = NextResponse.json({profile});
  response.cookies.set("tme3_profile", signProfile(profile), options);
  return response;
}
