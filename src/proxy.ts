import { NextResponse } from "next/server";
import { SENSITIVE_CACHE_HEADERS } from "@/lib/http-security";

export function proxy() {
  const response = NextResponse.next();
  for (const { key, value } of SENSITIVE_CACHE_HEADERS) {
    response.headers.set(key, value);
  }
  return response;
}

export const config = {
  matcher: [
    "/app/:path*",
    "/platform/:path*",
    "/login",
    "/forgot-password",
    "/reset-password",
    "/accept-invitation",
    "/invite",
  ],
};
