import { AdminPortal } from "./portal";

export const metadata = {title: "Administration"};
export default function AdminPage() {
  return <div className="shell workspace"><AdminPortal/></div>;
}
