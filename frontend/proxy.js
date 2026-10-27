import { NextResponse } from "next/server.js";

export function proxy() {
  if (process.env.PORTFOLIO_MODE === "1") {
    return new Response("Not Found", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*", "/invite/:path*", "/transfer/:path*"],
};
