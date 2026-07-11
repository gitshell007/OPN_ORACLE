import { SettingsHeader } from "@/components/auth/account-security";
import { ProductPreferences } from "@/components/navigation/product-preferences";

export default function Page() {
  return (
    <>
      <SettingsHeader active="preferences" />
      <ProductPreferences />
    </>
  );
}
