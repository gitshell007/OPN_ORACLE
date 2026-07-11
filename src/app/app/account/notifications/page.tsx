import { SettingsHeader } from "@/components/auth/account-security";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { NotificationPreferences } from "@/components/reporting/notifications";

export default function NotificationPreferencesPage() {
  return (
    <AuthBoundary permission="notifications.manage">
      <SettingsHeader active="notifications" />
      <NotificationPreferences />
    </AuthBoundary>
  );
}
