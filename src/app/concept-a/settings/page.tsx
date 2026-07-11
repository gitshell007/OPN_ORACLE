import { VectorSettings } from "@/components/concept-a/vector-settings";
import { SettingsHeader } from "@/components/auth/account-security";
export default function SettingsPage() {
  return (
    <>
      <SettingsHeader active="preferences" />
      <VectorSettings />
    </>
  );
}
