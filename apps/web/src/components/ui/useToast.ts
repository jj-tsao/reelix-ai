import { createContext, useContext } from "react";

export type ToastVariant = "default" | "success" | "destructive";

export type Toast = {
  id: string;
  title?: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number | null;
};

export type ToastContextValue = {
  toast: (t: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
};

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
