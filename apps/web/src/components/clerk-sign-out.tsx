"use client";

import { SignOutButton } from "@clerk/nextjs";
import { Button } from "./ui/button";

export default function ClerkSignOut() {
  return <SignOutButton redirectUrl="/"><Button variant="ghost">Sign out</Button></SignOutButton>;
}
