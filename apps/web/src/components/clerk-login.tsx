"use client";

import { SignIn } from "@clerk/nextjs";

export default function ClerkLogin({ next }: { next: string }) {
  return <SignIn routing="hash" forceRedirectUrl={next} />;
}
