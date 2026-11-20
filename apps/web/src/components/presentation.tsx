import Link from "next/link";
import { ArrowRight, LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./ui/button";

export function PageTitle({ section, title, children, action }: {
  section?: string; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return <div className="page-title"><div>
    {section && <p className="eyebrow">{section}</p>}
    <h1>{title}</h1>
    {children && <p className="lede">{children}</p>}
  </div>{action}</div>;
}

export function State({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={error ? "state state-error" : "state"} role={error ? "alert" : "status"}>{children}</div>;
}

export function SignInNotice({ next, children }: { next: string; children: ReactNode }) {
  return <div className="signin-notice">
    <LockKeyhole size={20} aria-hidden="true"/>
    <div><h3>Sign in to continue</h3><p>{children}</p></div>
    <Button asChild variant="primary"><Link href={"/login?next=" + encodeURIComponent(next)}>Sign in <ArrowRight size={16}/></Link></Button>
  </div>;
}
