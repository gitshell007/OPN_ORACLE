import { redirect } from "next/navigation";

export default function AdminHome() {
  redirect("/app/admin/members");
}
