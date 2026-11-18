import { Suspense } from "react";
import { PageTitle, State } from "@/components/presentation";
import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return <div className="shell workspace"><div className="narrow">
    <PageTitle title="Sign in">Access rankings and backtest reports.</PageTitle>
    <Suspense fallback={<State>Loading sign-in…</State>}><LoginForm/></Suspense>
  </div></div>;
}
