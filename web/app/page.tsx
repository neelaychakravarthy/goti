import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { GOTI_SESSION_COOKIE, GOTI_SESSION_VALUE } from "@/lib/auth";

export default async function RootPage() {
  const store = await cookies();
  const session = store.get(GOTI_SESSION_COOKIE);
  if (session?.value === GOTI_SESSION_VALUE) {
    redirect("/search");
  }
  redirect("/start");
}
