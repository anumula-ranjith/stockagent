import { AccountForm } from "@/components/account-form";

export const metadata = { title: "Your account", robots: { index: false } };
export default function AccountPage() { return <AccountForm mode="account"/>; }
