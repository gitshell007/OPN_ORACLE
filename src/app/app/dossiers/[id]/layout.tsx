import { DossierNavigation } from "@/components/navigation/product-navigation";

export default async function DossierLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <DossierNavigation dossierId={id} />
      {children}
    </>
  );
}
