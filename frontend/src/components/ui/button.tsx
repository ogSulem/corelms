import * as React from "react";

import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/cn";

type ButtonVariant = "primary" | "secondary" | "ghost" | "outline" | "destructive" | "link";
type ButtonSize = "default" | "sm" | "lg" | "icon";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
};

export const Button = React.forwardRef<
  HTMLButtonElement,
  ButtonProps
>(({ variant = "primary", size = "default", className, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  
  const variants: Record<ButtonVariant, string> = {
    primary:
      "bg-[#fe9900] text-zinc-950 shadow-sm hover:bg-[#f48f00] active:scale-[0.98] font-black uppercase tracking-widest text-[10px]",
    secondary:
      "bg-[#284e13] text-white shadow-sm hover:bg-[#21410f] active:scale-[0.98] font-black uppercase tracking-widest text-[10px]",
    destructive: "bg-red-600 text-white shadow-sm hover:bg-red-700 active:scale-[0.98] font-black uppercase tracking-widest text-[10px]",
    outline:
      "border-2 border-[#fe9900]/30 bg-white text-zinc-900 shadow-sm hover:bg-[#fe9900]/10 hover:border-[#fe9900]/45 active:scale-[0.98] font-black uppercase tracking-widest text-[10px]",
    ghost:
      "text-zinc-600 hover:text-zinc-950 hover:bg-zinc-50 active:scale-[0.98] font-black uppercase tracking-widest text-[10px]",
    link: "text-[#284e13] underline-offset-4 hover:underline font-black uppercase tracking-widest text-[10px]",
  };

  const sizes: Record<ButtonSize, string> = {
    default: "h-11 px-6 py-2",
    sm: "h-9 rounded-md px-3 text-xs",
    lg: "h-12 rounded-xl px-8 text-base",
    icon: "h-10 w-10",
  };

  return (
    <Comp
      className={cn(
        "inline-flex items-center justify-center transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#fe9900]/35",
        "disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className
      )}
      ref={ref}
      {...props}
    />
  );
});

Button.displayName = "Button";
