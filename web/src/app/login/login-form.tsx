"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth-card";
import { useLogin } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";

export function LoginForm({ justRegistered }: { justRegistered: boolean }) {
  const router = useRouter();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => router.push("/dashboard") });
  }

  return (
    <AuthCard
      title="Log in"
      footer={
        <>
          No account yet?{" "}
          <Link href="/register" className="font-medium text-slate-900 underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit}>
        {justRegistered && !login.isError ? (
          <FormMessage tone="info">Account created. You can log in now.</FormMessage>
        ) : null}
        {login.isError ? <FormMessage tone="error">{userMessage(login.error)}</FormMessage> : null}
        <Field
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <SubmitButton pending={login.isPending}>
          {login.isPending ? "Logging in…" : "Log in"}
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
