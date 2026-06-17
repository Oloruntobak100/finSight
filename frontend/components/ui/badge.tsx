import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<"span"> & { variant?: "default" | "secondary" | "success" | "warning" | "destructive" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variant === "default" && "bg-slate-800 text-slate-300",
        variant === "secondary" && "border border-slate-700 bg-slate-900/60 text-slate-400",
        variant === "success" && "bg-green-500/20 text-green-400",
        variant === "warning" && "bg-yellow-500/20 text-yellow-400",
        variant === "destructive" && "bg-red-500/20 text-red-400",
        className
      )}
      {...props}
    />
  );
}
