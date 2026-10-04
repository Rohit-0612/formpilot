import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { registered } = await searchParams;
  return <LoginForm justRegistered={registered === "1"} />;
}
