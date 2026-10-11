"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth-card";
import { useRegister } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";

// Mirrors the server rule for the hint only; the API is the authority (422 otherwise).
const PASSWORD_MIN_LENGTH = 8;

export default function RegisterPage() {
  const router = useRouter();
  const register = useRegister();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    register.mutate(
      { email, password },
      { onSuccess: () => router.push("/login?registered=1") },
    );
  }

  return (
    <AuthCard
      title="Create your account"
      footer={
        <>
          Already registered?{" "}
          <Link href="/login" className="font-medium text-slate-900 underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit}>
        {register.isError ? (
          <FormMessage tone="error">{userMessage(register.error)}</FormMessage>
        ) : null}
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
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN_LENGTH}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <SubmitButton pending={register.isPending}>
          {register.isPending ? "Creating account…" : "Create account"}
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
