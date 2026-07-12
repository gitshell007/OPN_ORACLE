export function safeNext(value: string | null, fallback = "/app"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  try {
    const decoded = decodeURIComponent(value);
    if (decoded.startsWith("//") || decoded.includes("\\")) return fallback;
  } catch { return fallback; }
  if (!(value === "/app" || value.startsWith("/app/") || value === "/concept-a" || value.startsWith("/concept-a/") || value === "/platform" || value.startsWith("/platform/"))) return fallback;
  return value;
}

export function authenticatedLanding(
  value: string | null,
  identity: {
    active_tenant_id: string | null;
    user: { platform_role: string | null };
  },
): string {
  const fallback =
    identity.user.platform_role === "super_admin" &&
    !identity.active_tenant_id
      ? "/platform/tenants"
      : "/app";
  return safeNext(value, fallback);
}
