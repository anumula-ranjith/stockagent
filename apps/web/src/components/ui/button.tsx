import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const variants = cva("button", {
  variants: { variant: { primary: "button-primary", secondary: "button-secondary", ghost: "button-ghost" } },
  defaultVariants: { variant: "primary" },
});

export function Button({
  className, variant, asChild = false, ...props
}: ComponentProps<"button"> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Element = asChild ? Slot : "button";
  return <Element className={cn(variants({ variant }), className)} {...props} />;
}
