import { PlatformTenantDetail } from "@/components/platform/platform-pages";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return <PlatformTenantDetail id={(await params).id} />;
}
