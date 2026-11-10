import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline"; loading?: boolean };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "primary", loading, children, disabled, ...rest }, ref) => (
  <button
    ref={ref}
    disabled={disabled || loading}
    className={cn(
      "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 font-semibold transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60",
      variant === "primary" && "bg-accent text-accent-ink shadow-sm hover:brightness-105",
      variant === "outline" && "border-2 border-line bg-surface hover:border-accent",
      variant === "ghost" && "hover:bg-surface-2",
      className,
    )}
    {...rest}
  >
    {loading && <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
    {children}
  </button>
));
Button.displayName = "Button";

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string };

export const Field = forwardRef<HTMLInputElement, FieldProps>(({ label, error, id, className, ...rest }, ref) => {
  const fid = id ?? rest.name;
  return (
    <label htmlFor={fid} className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <input
        ref={ref}
        id={fid}
        aria-invalid={!!error}
        className={cn(
          "w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none transition focus:border-accent",
          error && "border-bad",
          className,
        )}
        {...rest}
      />
      {error && (
        <span role="alert" className="text-sm text-bad">
          {error}
        </span>
      )}
    </label>
  );
});
Field.displayName = "Field";

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement> & { "data-tour"?: string }) {
  return <div {...rest} className={cn("rounded-2xl border border-line bg-surface p-5 shadow-sm", className)}>{children}</div>;
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-full border-2 px-3 py-1.5 text-sm font-medium transition",
            o.value === value ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:border-accent",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A visible heading above a control whose own label is only for screen readers (e.g. Segmented). */
export function Labelled({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium" aria-hidden>{text}</p>
      {children}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-1">
      <span>{label}</span>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cn("relative h-7 w-12 rounded-full transition", checked ? "bg-accent" : "bg-line")}
      >
        <span className={cn("absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all", checked ? "left-6" : "left-1")} />
      </button>
    </label>
  );
}
