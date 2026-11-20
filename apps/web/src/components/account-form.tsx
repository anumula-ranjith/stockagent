"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { useSession, usesClerk } from "./providers";
import { PageTitle, SignInNotice, State } from "./presentation";
import { Button } from "./ui/button";

export function PasswordField({ label, name, current = false }: { label: string; name: string; current?: boolean }) {
  const [visible, setVisible] = useState(false);
  return <div className="field">
    <label htmlFor={name}>{label}</label>
    <div className="password-input">
      <input id={name} name={name} type={visible ? "text" : "password"} required
        minLength={current ? 1 : 12} maxLength={256} autoComplete={current ? "current-password" : "new-password"}/>
      <button type="button" onClick={() => setVisible(!visible)} aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`} aria-pressed={visible}>
        {visible ? "Hide" : "Show"}
      </button>
    </div>
  </div>;
}

type Mode = "signup" | "forgot-password" | "reset-password" | "verify-email" | "account";
const titles: Record<Mode, string> = {
  signup: "Create an account", "forgot-password": "Forgot password?", "reset-password": "Set a new password",
  "verify-email": "Verify your email", account: "Your account",
};
const descriptions: Record<Mode, string> = {
  signup: "Create your account to access rankings and backtest reports.",
  "forgot-password": "Enter your account email and we’ll send you a reset link.",
  "reset-password": "Choose a password with at least 12 characters.",
  "verify-email": "Confirm your email address to activate your account.",
  account: "Manage your sign-in details.",
};

export function AccountForm({ mode }: { mode: Mode }) {
  const session = useSession();
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  useEffect(() => {
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (value) {
      setToken(value);
      window.history.replaceState(null, "", window.location.pathname);
    }
    setReady(true);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const password = String(fields.get("password") || "");
    if (password && password !== fields.get("confirm_password")) {
      setFailed(true);
      setMessage("The passwords do not match.");
      return;
    }
    let path: string = mode;
    let body: Record<string, string> = { email: String(fields.get("email") || "") };
    if (mode === "signup") { path = "register"; body.password = password; }
    if (mode === "verify-email") {
      path = token ? "verify-email" : "resend-verification";
      if (token) body = { token };
    }
    if (mode === "reset-password") body = { token, password };
    if (mode === "account") {
      path = "change-password";
      body = { current_password: String(fields.get("current_password")), password };
    }
    setPending(true);
    setMessage("");
    setFailed(false);
    try {
      const result = await api<{ message: string }>(`/${path}`, { method: "POST", body: JSON.stringify(body) });
      setMessage(result.message);
      setComplete(true);
      form.reset();
      if (mode === "account" || mode === "reset-password") void session.refetch();
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Please try again.");
    } finally { setPending(false); }
  }

  const needsPassword = mode === "signup" || mode === "reset-password" || mode === "account";
  const needsEmail = mode === "signup" || mode === "forgot-password" || (mode === "verify-email" && !token);
  const submitLabel = mode === "signup" ? "Create account" : mode === "forgot-password" ? "Send reset link"
    : mode === "verify-email" ? token ? "Verify email" : "Send verification email" : "Update password";
  let content;
  if (usesClerk) content = <p>Manage your account through <Link className="text-link" href="/login">Sign in</Link>.</p>;
  else if (!ready || (mode === "account" && session.isPending)) content = <State>Loading…</State>;
  else if (complete) content = <div className="controls">
    <p role="status">{message}</p>
    <Link className="text-link" href="/login">Go to sign in</Link>
    {(mode === "signup" || mode === "verify-email") && <Link className="text-link" href="/verify-email" onClick={() => { setToken(""); setComplete(false); setMessage(""); }}>Request another verification email</Link>}
    {mode === "forgot-password" && <Button variant="secondary" onClick={() => { setComplete(false); setMessage(""); }}>Try another email</Button>}
  </div>;
  else if (mode === "account" && session.isError) content = <State error>Unable to load your account. Please refresh and try again.</State>;
  else if (mode === "account" && !session.data) content = <SignInNotice next="/account">Sign in to change your password.</SignInNotice>;
  else if (mode === "reset-password" && !token) content = <p>This reset link is missing or expired. <Link className="text-link" href="/forgot-password">Request a new link</Link></p>;
  else content = <>
    {mode === "account" && <p className="mb-5">Signed in as <strong>{session.data?.email}</strong></p>}
    <form className="controls" onSubmit={e => void submit(e)}>
      {needsEmail && <label className="field">Email<input name="email" type="email" required autoComplete="email"/></label>}
      {mode === "account" && <PasswordField label="Current password" name="current_password" current/>}
      {needsPassword && <>
        <PasswordField label={mode === "signup" ? "Password" : "New password"} name="password"/>
        <p className="subtle">Use 12–256 characters. A few unrelated words work well.</p>
        <PasswordField label="Confirm password" name="confirm_password"/>
      </>}
      {mode === "account" && <p className="subtle">Changing your password signs you out on all devices.</p>}
      <Button type="submit" disabled={pending}>{pending ? "Please wait…" : submitLabel}</Button>
    </form>
    {message && <p className={failed ? "state-error mt-3" : "subtle mt-3"} role={failed ? "alert" : "status"}>{message}</p>}
    {failed && token && <Link className="text-link mt-3" href={mode === "verify-email" ? "/verify-email" : "/forgot-password"}
      onClick={() => { if (mode === "verify-email") { setToken(""); setMessage(""); } }}>Request a new link</Link>}
    <p className="mt-5"><Link className="text-link" href="/login">Back to sign in</Link></p>
  </>;
  return <div className="shell workspace"><div className="narrow">
    <PageTitle title={titles[mode]}>{descriptions[mode]}</PageTitle>
    <div className="surface login-box">{content}</div>
  </div></div>;
}
