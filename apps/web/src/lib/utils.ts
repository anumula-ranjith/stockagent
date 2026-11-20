import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...values: ClassValue[]) {
  return twMerge(clsx(values));
}

export const dateLabel = (value: string) => new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium", timeZone: "UTC",
}).format(new Date(value.length === 10 ? `${value}T00:00:00Z` : value));

export const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
});
