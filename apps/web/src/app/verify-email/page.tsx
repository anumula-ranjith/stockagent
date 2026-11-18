import { AccountForm } from "@/components/account-form";

export const metadata = { title: "Verify email", robots: { index: false }, referrer: "no-referrer" };
export default function VerifyEmailPage() { return <AccountForm mode="verify-email"/>; }
