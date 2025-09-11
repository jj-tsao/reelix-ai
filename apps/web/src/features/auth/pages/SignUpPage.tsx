import { useState } from "react";
import { Link } from "react-router-dom";
import { signUpWithPassword, sendMagicLink, signInWithOAuth } from "../api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";

export default function SignUpPage() {
  const OAUTH_ENABLED = false;
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [usePassword, setUsePassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toast({ title: "Name is required", description: "Please enter your name.", variant: "destructive" });
      return;
    }
    if (usePassword && password !== confirm) {
      toast({
        title: "Passwords don't match",
        description: "Please re-enter your password.",
        variant: "destructive",
      });
      return;
    }
    setSubmitting(true);
    try {
      if (usePassword) {
        const res = await signUpWithPassword(email, password, name.trim());
        if (!res.ok) {
          toast({ title: "Sign up failed", description: res.error, variant: "destructive" });
          return;
        }
        try { localStorage.setItem("pendingDisplayName", name.trim()); } catch (e) { void e; }
        toast({ title: "Check your email", description: "Confirm your address to finish sign up.", variant: "success", duration: null });
      } else {
        const res = await sendMagicLink(email, name.trim());
        if (!res.ok) {
          toast({ title: "Sign up failed", description: res.error, variant: "destructive" });
          return;
        }
        try { localStorage.setItem("pendingDisplayName", name.trim()); } catch (e) { void e; }
        toast({ title: "Check your email", description: "We sent a link to finish creating your Reelix account.", variant: "success", duration: null });
      }
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
          {OAUTH_ENABLED && (
            <>
              <div className="space-y-2">
                <Button type="button" variant="outline" className="w-full" onClick={() => signInWithOAuth("google")}>
                  <svg aria-hidden="true" viewBox="0 0 18 18" className="size-4 shrink-0 -ml-0.5"><path fill="#EA4335" d="M9 7.65v3.51h4.94c-.2 1.3-1.62 3.73-4.94 3.73-2.98 0-5.4-2.42-5.4-5.4S6.02 4.1 9 4.1c1.68 0 2.82.71 3.42 1.31l2.37-2.37C13.2 1.76 11.28.9 9 .9 4.53.9 1 4.43 1 8.9s3.53 8 8 8c4.6 0 7.63-3.23 7.63-7.78 0-.52-.05-.86-.12-1.27H9z"/><path fill="#34A853" d="M3.62 10.54A5.4 5.4 0 0 1 3.6 7.3l-2.52-1.96A8.004 8.004 0 0 0 1 8.9c0 1.26.3 2.44.84 3.49l2.78-1.85z"/><path fill="#FBBC05" d="M9 3.3c1.68 0 2.82.71 3.42 1.31l2.37-2.37C13.2 1.76 11.28.9 9 .9 5.6.9 2.68 2.85 1.72 5.34l2.88 2.23C5.02 5.53 6.82 3.3 9 3.3z"/><path fill="#4285F4" d="M9 16.9c2.48 0 4.56-.82 6.06-2.25l-2.66-2.06c-.73.5-1.71.89-3.4.89-2.16 0-3.99-1.45-4.63-3.39l-2.78 1.85C3.63 14.93 6.09 16.9 9 16.9z"/></svg>
                  Continue with Google
                </Button>
                <Button type="button" variant="outline" className="w-full" onClick={() => signInWithOAuth("apple")}>
                  <svg aria-hidden="true" viewBox="0 0 24 24" preserveAspectRatio="xMidYMid meet" className="size-4 shrink-0 -ml-0.5 relative top-[1px] text-neutral-300"><path fill="currentColor" d="M16.365 1.43c0 1.14-.46 2.23-1.2 3.03-.78.83-2.06 1.47-3.2 1.36-.14-1.12.5-2.29 1.23-3.03.82-.85 2.2-1.46 3.17-1.36zM20.5 17.1c-.61 1.4-1.34 2.77-2.42 3.99-1.04 1.18-2.37 2.65-4.1 2.68-1.72.03-2.17-.86-4.05-.86-1.89 0-2.37.84-4.09.89-1.72.05-3.03-1.29-4.08-2.46C.9 19.95-.4 16.4.74 13.46c.64-1.69 1.77-3.58 3.22-3.63 1.52-.06 2.46.98 4.14.98 1.66 0 2.47-.98 4.17-.95 1.37.03 2.24.7 2.86 1.52-2.51 1.38-2.36 4.99.41 6.16.73.32 1.92.51 3-.44-.08.22-.15.44-.24.64z"/></svg>
                  Continue with Apple
                </Button>
              </div>
              <div className="my-2 flex items-center gap-2 text-xs text-muted-foreground"><div className="h-px flex-1 bg-border/70" /><span>or use email</span><div className="h-px flex-1 bg-border/70" /></div>
            </>
          )}
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
          {usePassword && (
            <>
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
            </>
          )}
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Please wait…" : usePassword ? "Create Account" : "Email me a link"}
          </Button>
          {!usePassword && (
            <p className="text-xs text-muted-foreground text-center">No password needed. We’ll create your account when you open the link.</p>
          )}
          <div className="text-center">
            <button type="button" className="text-sm underline underline-offset-4 text-primary" onClick={() => setUsePassword((v) => !v)}>
              {usePassword ? "Use email link instead" : "Use password instead"}
            </button>
          </div>
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
