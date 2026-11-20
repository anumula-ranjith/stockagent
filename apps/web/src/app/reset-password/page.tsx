import { AccountForm } from "@/components/account-form";

export const metadata = { title: "Reset password", robots: { index: false }, referrer: "no-referrer" };
export default function ResetPasswordPage() { return <AccountForm mode="reset-password"/>; }
