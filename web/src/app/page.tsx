import { redirect } from "next/navigation";

export default function Home() {
  // The dashboard sends visitors without a session on to /login.
  redirect("/dashboard");
}
