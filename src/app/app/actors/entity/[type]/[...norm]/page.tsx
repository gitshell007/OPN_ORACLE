import { notFound, redirect } from "next/navigation";
import { decodeEntityPathName, entityRoute } from "@/lib/entity-route";

const supportedTypes = new Set(["company", "person"]);

/**
 * Legacy path: /app/actors/entity/{type}/{name with spaces or %20...}
 * Redirects to the canonical query form so Next soft-navigation never puts
 * spaces into the router-state tree header.
 */
export default async function LegacyEntityPathRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ type: string; norm: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { type, norm } = await params;
  if (!supportedTypes.has(type)) notFound();

  const name = decodeEntityPathName(norm);
  if (name.length < 2) notFound();

  const query = await searchParams;
  const extras: { tab?: string; tool?: string } = {};
  const tab = Array.isArray(query.tab) ? query.tab[0] : query.tab;
  const tool = Array.isArray(query.tool) ? query.tool[0] : query.tool;
  if (tab) extras.tab = tab;
  if (tool) extras.tool = tool;

  redirect(entityRoute(type as "company" | "person", name, extras));
}
