import { AccountForm } from "@/components/account-form";

export const metadata = { title: "Create an account", robots: { index: false } };
export default function SignupPage() { return <AccountForm mode="signup"/>; }
