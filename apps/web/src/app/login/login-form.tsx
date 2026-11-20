"use client";

import { ArrowRight } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, ApiError, type LoginBody } from "@/lib/api";
import { usesClerk } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { PasswordField } from "@/components/account-form";

const ClerkLogin = dynamic(() => import("@/components/clerk-login"), { ssr: false });

export function LoginForm() {
  const search = useSearchParams();
  const candidate = search.get("next");
  const next = candidate && /^\/(dashboard|screener|stocks(?:\/[a-z0-9.%&_-]+)?|backtest|methodology|account)(?:\?|$)/i.test(candidate)
    ? candidate : "/dashboard";
  const [message, setMessage] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const body: LoginBody = { email: String(data.get("email")), password: String(data.get("password")) };
    setPending(true);
    setMessage("");
    setNeedsVerification(false);
    try {
      await api("/login", { method: "POST", body: JSON.stringify(body) });
      window.location.assign(next);
    } catch (error) {
      setNeedsVerification(error instanceof ApiError && error.status === 403);
      setMessage(error instanceof ApiError && error.status === 401
        ? "The email or password is incorrect. Please try again."
        : error instanceof Error ? error.message : "Sign-in failed. Try again.");
      setPending(false);
    }
  }
  if (usesClerk) return <ClerkLogin next={next}/>;
  return <div className="surface login-box">
    <form className="controls" method="post" action="/backend/login" onSubmit={e => void submit(e)}>
      <label className="field">Email<input type="email" name="email" autoComplete="username" required/></label>
      <PasswordField label="Password" name="password" current/>
      <Link className="text-link" href="/forgot-password">Forgot password?</Link>
      <Button type="submit" disabled={pending}>{pending ? "Signing in…" : "Sign in"} <ArrowRight size={17}/></Button>
    </form>
    {message && <p className="state-error mt-3" role="alert">{message}</p>}
    {needsVerification && <Link className="text-link mt-3" href="/verify-email">Resend verification email</Link>}
    <p className="mt-5">New to QUANTORA? <Link className="text-link" href="/signup">Create an account</Link></p>
  </div>;
}
