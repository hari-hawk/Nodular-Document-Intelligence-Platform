import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Tiny className helper — clsx for conditional joins + tailwind-merge to
 * de-duplicate conflicting tailwind classes (e.g. `p-2` vs `p-4`).
 * Used by every component in this app.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
