import { useState } from "react";
import { Link } from "react-router-dom";
import { signUpWithPassword } from "../api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export default function SignUpPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toast({ title: "Name is required", description: "Please enter your name.", variant: "destructive" });
      return;
    }
    if (password !== confirm) {
      toast({
        title: "Passwords don't match",
        description: "Please re-enter your password.",
        variant: "destructive",
      });
      return;
    }
    setSubmitting(true);
    try {
      const res = await signUpWithPassword(email, password, name.trim());
      if (!res.ok) {
        toast({
          title: "Sign up failed",
          description: res.error,
          variant: "destructive",
        });
        return;
      }
      try { localStorage.setItem("pendingDisplayName", name.trim()); } catch {}
      toast({
        title: "Check your email",
        description: "Confirm your address to finish sign up.",
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
            Create Account
          </h1>
          <div className="space-y-2">
            <label className="block text-sm font-medium" htmlFor="name">
              Name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="Your name"
            />
          </div>
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
          <div className="space-y-2">
            <label className="block text-sm font-medium" htmlFor="confirm">
              Confirm Password
            </label>
            <input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={6}
              className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="••••••••"
            />
          </div>
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Please wait…" : "Create Account"}
          </Button>
        </form>
        <div className="mt-4 rounded-md border bg-muted/30 p-3">
          <p className="mb-2 text-sm text-muted-foreground text-center">
            Already have an account?
          </p>
          <Button variant="outline" className="w-full" asChild>
            <Link to="/auth/signin">Sign In</Link>
          </Button>
        </div>
      </section>
    </main>
  );
}
