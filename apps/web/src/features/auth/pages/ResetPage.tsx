import { useState } from "react";
import { Link } from "react-router-dom";
import { requestPasswordReset } from "../api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export default function ResetPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await requestPasswordReset(email);
      if (!res.ok) {
        toast({
          title: "Reset failed",
          description: res.error,
          variant: "destructive",
        });
        return;
      }
      toast({
        title: "Check your email",
        description: "Follow the link to set a new password.",
        variant: "success",
        duration: null,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <section className="mx-auto w-full max-w-md">
        <form onSubmit={onSubmit} className="space-y-4 rounded-lg border p-4">
          <h1 className="mb-3 text-xl md:text-2xl font-semibold tracking-tight text-center">
            Reset Password
          </h1>
          <div className="space-y-2">
            <label className="block text-sm font-medium" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="you@example.com"
            />
          </div>
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Please wait…" : "Send Reset Link"}
          </Button>
        </form>
        <p className="mt-3 text-sm text-muted-foreground text-center">
          Remembered it?{" "}
          <Link to="/auth/signin" className="underline underline-offset-4">
            Back to Sign In
          </Link>
        </p>
      </section>
    </main>
  );
}
