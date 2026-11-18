import { AccountForm } from "@/components/account-form";

export const metadata = { title: "Forgot password", robots: { index: false } };
export default function ForgotPasswordPage() { return <AccountForm mode="forgot-password"/>; }
