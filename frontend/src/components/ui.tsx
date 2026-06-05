"use client";

import { cn } from "@/lib/cn";
import { forwardRef } from "react";

/**
 * Hand-rolled primitives. We deliberately AVOID shadcn/ui for v1 — it
 * pulls in 15+ Radix packages for what amounts to a handful of styled
 * divs at this UI's complexity. When the design demands accessible
 * combobox / dialog / popover behaviour, the shadcn CLI is one
 * `npx shadcn add ...` away and these components have the same prop
 * shape so the swap is mechanical.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Button
// ─────────────────────────────────────────────────────────────────────────────
type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
type ButtonSize = "sm" | "md" | "lg";

const buttonVariantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 hover:bg-brand-700 text-white shadow-sm " +
    "disabled:bg-brand-300 dark:disabled:bg-brand-800",
  secondary:
    "bg-[rgb(var(--surface-muted))] hover:bg-slate-200 dark:hover:bg-slate-700 " +
    "text-[rgb(var(--fg))] border border-[rgb(var(--border))]",
  ghost:
    "hover:bg-[rgb(var(--surface-muted))] text-[rgb(var(--fg))]",
  destructive:
    "bg-red-600 hover:bg-red-700 text-white shadow-sm",
};

const buttonSizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-6 text-base",
};

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "primary", size = "md", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium " +
          "transition-colors focus-visible:outline-none focus-visible:ring-2 " +
          "focus-visible:ring-brand-500 focus-visible:ring-offset-2 " +
          "disabled:cursor-not-allowed disabled:opacity-50",
        buttonVariantClasses[variant],
        buttonSizeClasses[size],
        className,
      )}
      {...props}
    />
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Card
// ─────────────────────────────────────────────────────────────────────────────
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] " +
          "shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 border-b border-[rgb(var(--border))]", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-base font-semibold", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-[rgb(var(--fg-muted))] mt-1", className)} {...props} />;
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tabs — controlled, no Radix. State lives in the parent.
// ─────────────────────────────────────────────────────────────────────────────
type TabsProps = {
  value: string;
  onValueChange: (v: string) => void;
  tabs: Array<{ value: string; label: string; badge?: string | number }>;
  className?: string;
};

export function Tabs({ value, onValueChange, tabs, className }: TabsProps) {
  return (
    <div className={cn("border-b border-[rgb(var(--border))] flex gap-1", className)}>
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onValueChange(t.value)}
          className={cn(
            "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            value === t.value
              ? "border-brand-500 text-brand-600 dark:text-brand-400"
              : "border-transparent text-[rgb(var(--fg-muted))] hover:text-[rgb(var(--fg))]",
          )}
        >
          {t.label}
          {t.badge !== undefined && t.badge !== "" && (
            <span
              className={cn(
                "ml-2 inline-flex items-center justify-center text-xs px-1.5 py-0.5 rounded-full",
                value === t.value
                  ? "bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-200"
                  : "bg-[rgb(var(--surface-muted))]",
              )}
            >
              {t.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Badge — pill-shaped severity / status indicators.
// ─────────────────────────────────────────────────────────────────────────────
type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
const badgeToneClasses: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  danger:  "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  info:    "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200",
  brand:   "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full",
        badgeToneClasses[tone],
        className,
      )}
      {...props}
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Input + Textarea
// ─────────────────────────────────────────────────────────────────────────────
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "h-9 w-full rounded-md border border-[rgb(var(--border))] " +
            "bg-[rgb(var(--surface))] px-3 text-sm " +
            "focus-visible:outline-none focus-visible:ring-2 " +
            "focus-visible:ring-brand-500 focus-visible:ring-offset-2 " +
            "disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          "min-h-[80px] w-full rounded-md border border-[rgb(var(--border))] " +
            "bg-[rgb(var(--surface))] p-3 text-sm font-mono " +
            "focus-visible:outline-none focus-visible:ring-2 " +
            "focus-visible:ring-brand-500 focus-visible:ring-offset-2",
          className,
        )}
        {...props}
      />
    );
  },
);

// ─────────────────────────────────────────────────────────────────────────────
// Empty + Loading states
// ─────────────────────────────────────────────────────────────────────────────
export function EmptyState({ title, subtitle, icon }: { title: string; subtitle?: string; icon?: React.ReactNode }) {
  return (
    <div className="text-center py-12 px-6">
      {icon && <div className="mx-auto mb-3 text-[rgb(var(--fg-muted))]">{icon}</div>}
      <h3 className="text-sm font-semibold">{title}</h3>
      {subtitle && <p className="mt-1 text-sm text-[rgb(var(--fg-muted))]">{subtitle}</p>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "h-4 w-4 border-2 border-brand-500 border-t-transparent rounded-full animate-spin",
        className,
      )}
      role="status"
      aria-label="loading"
    />
  );
}

/**
 * Skeleton placeholder block. Much cheaper visually than a spinner
 * for list/table loads — shows the SHAPE of the content that's
 * coming, so the layout doesn't jump on data arrival.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded bg-[rgb(var(--surface-muted))]",
        className,
      )}
    />
  );
}

/**
 * Pre-built table-row skeleton — rows with two columns of varying
 * widths. Used by tables that haven't loaded yet so the page reserves
 * the right vertical space and doesn't shift around on data arrival.
 */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-3 w-1/4" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

/**
 * Tiny MDI logomark. Intentionally minimal — a brand-coloured
 * rounded square with `M` glyph, sized to fit alongside text.
 * Replace with a designer mark once the brand book is written;
 * for now this is enough to signal "this is a product, not a
 * raw admin tool".
 */
export function Logomark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-md",
        "bg-gradient-to-br from-brand-500 to-brand-700",
        "text-white text-xs font-bold tracking-tight",
        className,
      )}
      aria-hidden="true"
    >
      M
    </span>
  );
}
