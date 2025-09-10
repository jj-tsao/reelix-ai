import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { signInWithPassword } from "../api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await signInWithPassword(email, password);
      if (!res.ok) {
        toast({ title: "Sign in failed", description: res.error, variant: "destructive" });
        return;
      }
      toast({ title: "Signed in", description: "Welcome back!", variant: "success" });
      navigate("/");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <section className="mx-auto w-full max-w-md">
        <form onSubmit={onSubmit} className="space-y-4 rounded-lg border p-4">
          <h1 className="mb-3 text-xl md:text-2xl font-semibold tracking-tight text-center">Sign In</h1>
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
          <div className="space-y-2">
            <label className="block text-sm font-medium" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="••••••••"
            />
          </div>
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Please wait…" : "Sign In"}
          </Button>
        </form>
        <div className="mt-4 rounded-md border bg-muted/30 p-3">
          <p className="mb-2 text-sm text-muted-foreground text-center">New to Reelix?</p>
          <Button variant="outline" className="w-full" asChild>
            <Link to="/auth/signup">Create Account</Link>
          </Button>
        </div>
        <p className="mt-3 text-sm text-muted-foreground text-center">
          <Link to="/auth/reset" className="underline underline-offset-4">Forgot password?</Link>
        </p>
        
      </section>
    </main>
  );
}
