import { AuthBoundary } from "@/components/auth/auth-boundary";
import { NotificationCenter } from "@/components/reporting/notifications";

export default function NotificationsPage() {
  return (
    <AuthBoundary permission="notifications.read">
      <NotificationCenter />
    </AuthBoundary>
  );
}
