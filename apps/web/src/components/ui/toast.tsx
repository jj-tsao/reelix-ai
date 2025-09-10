import React, { createContext, useContext, useMemo, useState } from "react";

type ToastVariant = "default" | "success" | "destructive";

type Toast = {
  id: string;
  title?: string;
  description?: string;
  variant?: ToastVariant;
  // When null, toast is sticky and must be dismissed manually
  duration?: number | null;
};

type ToastContextValue = {
  toast: (t: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const api = useMemo<ToastContextValue>(() => ({
    toast: ({ title, description, duration = 3500, variant = "default" }) => {
      const id = crypto.randomUUID();
      const item: Toast = { id, title, description, duration, variant };
      setToasts((t) => [...t, item]);
      if (duration !== null && duration! > 0) {
        window.setTimeout(() => {
          setToasts((t) => t.filter((x) => x.id !== id));
        }, duration);
      }
      return id;
    },
    dismiss: (id: string) => setToasts((t) => t.filter((x) => x.id !== id)),
  }), []);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={[
              "rounded-md border p-3 shadow-sm bg-background text-foreground",
              t.variant === "success" && "border-green-500/60",
              t.variant === "destructive" && "border-red-500/60",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <div className="flex items-start gap-3">
              <div className="flex-1">
                {t.title ? <div className="text-sm font-medium">{t.title}</div> : null}
                {t.description ? (
                  <div className="mt-1 text-xs text-muted-foreground">{t.description}</div>
                ) : null}
              </div>
              <button
                aria-label="Dismiss"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => api.dismiss(t.id)}
              >
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
