"use client";

import { ArrowRight } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, type LoginBody } from "@/lib/api";
import { usesClerk } from "@/components/providers";
import { Button } from "@/components/ui/button";

const ClerkLogin = dynamic(() => import("@/components/clerk-login"), { ssr: false });

export function LoginForm() {
  const search = useSearchParams();
  const candidate = search.get("next");
  const next = candidate && /^\/(dashboard|stocks(?:\/[a-z0-9.%&_-]+)?|backtest|methodology)(?:\?|$)/i.test(candidate)
    ? candidate : "/dashboard";
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(false);
  const [setup, setSetup] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>, signup: boolean) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const body: LoginBody = { email: String(data.get("email")), password: String(data.get("password")) };
    setPending(true);
    setMessage("");
    try {
      await api(signup ? "/signup" : "/login", {
        method: "POST", body: JSON.stringify(body),
        headers: signup ? { "X-Bootstrap-Signup-Token": String(data.get("bootstrap")) } : undefined,
      });
      if (!signup) { window.location.assign(next); return; }
      form.reset();
      setSetup(false);
      setEmail(body.email);
      setFailed(false);
      setMessage("Administrator created. Sign in with your password.");
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Sign-in failed. Try again.");
    } finally { setPending(false); }
  }
  if (usesClerk) return <ClerkLogin next={next}/>;
  return <div className="surface login-box">
    <form className="controls" method="post" action="/backend/login" onSubmit={e => void submit(e, false)}>
      <label className="field">Email<input type="email" name="email" autoComplete="username" required value={email}
        onChange={e => setEmail(e.target.value)}/></label>
      <label className="field">Password<input name="password" type="password" autoComplete="current-password" required maxLength={256}/></label>
      <Button type="submit" disabled={pending}>Sign in <ArrowRight size={17}/></Button>
    </form>
    {message && <p className={failed ? "state-error mt-3" : "subtle mt-3"} role={failed ? "alert" : "status"}>{message}</p>}
    <details open={setup} onToggle={e => setSetup(e.currentTarget.open)}>
      <summary>Set up the first administrator</summary>
      <form className="controls" method="post" action="/backend/signup" onSubmit={e => void submit(e, true)}>
        <label className="field">Administrator email<input type="email" name="email" required autoComplete="username"/></label>
        <label className="field">New password<input type="password" name="password" required minLength={12} maxLength={256} autoComplete="new-password"/></label>
        <label className="field">Bootstrap token<input type="password" name="bootstrap" required autoComplete="off"/></label>
        <Button variant="secondary" type="submit" disabled={pending}>Create administrator</Button>
      </form>
    </details>
  </div>;
}
