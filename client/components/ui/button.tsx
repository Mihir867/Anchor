import React from "react";
import { Spinner } from "./icons";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "md" | "lg" | "field";

const BASE =
  "relative inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap select-none " +
  "transition-colors duration-[120ms] ease-out cursor-pointer active:translate-y-px " +
  "disabled:pointer-events-none disabled:text-fg-disabled aria-busy:pointer-events-none";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover active:bg-accent-active disabled:bg-bg-muted",
  secondary:
    "border border-border bg-bg text-fg hover:bg-bg-subtle hover:border-border-strong active:bg-bg-muted disabled:bg-bg",
  ghost: "text-fg-2 hover:bg-bg-subtle hover:text-fg active:bg-bg-muted",
  destructive: "bg-danger text-white hover:bg-danger-hover disabled:bg-bg-muted",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 pointer-coarse:h-11",
  md: "h-8 px-3 pointer-coarse:h-11",
  lg: "h-10 px-4 pointer-coarse:h-11",
  /* matches the hero URL field: 48px on phones, 40px (44px on touch) from sm up */
  field: "h-12 px-4 sm:h-10 sm:pointer-coarse:h-11",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", extra = "") {
  return `${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${extra}`;
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Keeps the label and size, adds a spinner and blocks clicks. */
  loading?: boolean;
  ref?: React.Ref<HTMLButtonElement>;
}

export function Button({ variant = "primary", size = "md", loading, className = "", children, type = "button", ...rest }: ButtonProps) {
  return (
    <button type={type} aria-busy={loading || undefined} className={buttonClass(variant, size, className)} {...rest}>
      {loading && <Spinner className="w-3.5 h-3.5" />}
      {children}
    </button>
  );
}

/** Square icon-only button: always has an accessible name and a tooltip. */
export function IconButton({
  label,
  className = "",
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex items-center justify-center w-8 h-8 pointer-coarse:w-11 pointer-coarse:h-11 rounded-md text-fg-2 hover:bg-bg-subtle hover:text-fg active:bg-bg-muted transition-colors duration-[120ms] ease-out cursor-pointer disabled:pointer-events-none disabled:text-fg-disabled ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
