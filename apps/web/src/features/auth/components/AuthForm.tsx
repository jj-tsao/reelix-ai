import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { requestPasswordReset, signInWithPassword, signUpWithPassword } from "../api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";

type Mode = "signin" | "signup" | "reset";

export default function AuthForm() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (mode === "signin") {
        const res = await signInWithPassword(email, password);
        if (!res.ok) {
          toast({ title: "Sign in failed", description: res.error, variant: "destructive" });
          return;
        }
        toast({ title: "Signed in", description: "Welcome back!", variant: "success" });
        navigate("/");
      } else {
        if (password !== confirmPassword) {
          toast({ title: "Passwords don't match", description: "Please re-enter your password.", variant: "destructive" });
          return;
        }
        const res = await signUpWithPassword(email, password);
        if (!res.ok) {
          toast({ title: "Sign up failed", description: res.error, variant: "destructive" });
          return;
        }
        toast({ title: "Check your email", description: "Confirm your address to finish sign up.", variant: "success", duration: null });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-md">
      <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
        <TabsList className="w-full">
          <TabsTrigger value="signin">Sign In</TabsTrigger>
          <TabsTrigger value="signup">Sign Up</TabsTrigger>
          <TabsTrigger value="reset">Reset</TabsTrigger>
        </TabsList>
        <TabsContent value="signin">
          <AuthFields
            email={email}
            password={password}
            setEmail={setEmail}
            setPassword={setPassword}
            onSubmit={onSubmit}
            submitting={submitting}
            cta="Sign In"
            onForgot={() => setMode("reset")}
          />
        </TabsContent>
        <TabsContent value="signup">
          <AuthFields
            email={email}
            password={password}
            setEmail={setEmail}
            setPassword={setPassword}
            confirm={confirmPassword}
            setConfirm={setConfirmPassword}
            onSubmit={onSubmit}
            submitting={submitting}
            cta="Create Account"
            onForgot={() => setMode("reset")}
          />
        </TabsContent>
        <TabsContent value="reset">
          <ResetFields
            email={email}
            setEmail={setEmail}
            submitting={submitting}
            onSubmit={async (e) => {
              e.preventDefault();
              setSubmitting(true);
              const res = await requestPasswordReset(email);
              setSubmitting(false);
              if (!res.ok) {
                toast({ title: "Reset failed", description: res.error, variant: "destructive" });
                return;
              }
              toast({ title: "Check your email", description: "Follow the link to set a new password.", variant: "success" });
              setMode("signin");
            }}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AuthFields(props: {
  email: string;
  password: string;
  setEmail: (v: string) => void;
  setPassword: (v: string) => void;
  confirm?: string;
  setConfirm?: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  submitting: boolean;
  cta: string;
  onForgot: () => void;
}) {
  const { email, password, setEmail, setPassword, confirm, setConfirm, onSubmit, submitting, cta, onForgot } = props;
  return (
    <form onSubmit={onSubmit} className="mt-4 space-y-4 rounded-lg border p-4">
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
      {typeof confirm === "string" && typeof setConfirm === "function" ? (
        <div className="space-y-2">
          <label className="block text-sm font-medium" htmlFor="confirm-password">
            Confirm Password
          </label>
          <input
            id="confirm-password"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            minLength={6}
            className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            placeholder="••••••••"
          />
        </div>
      ) : null}
      <div className="flex items-center justify-between gap-3">
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Please wait…" : cta}
        </Button>
      </div>
      <div className="text-right">
        <button type="button" className="text-sm text-primary underline underline-offset-4" onClick={onForgot}>
          Forgot your password?
        </button>
      </div>
    </form>
  );
}

function ResetFields(props: {
  email: string;
  setEmail: (v: string) => void;
  submitting: boolean;
  onSubmit: (e: React.FormEvent) => void;
}) {
  const { email, setEmail, submitting, onSubmit } = props;
  return (
    <form onSubmit={onSubmit} className="mt-4 space-y-4 rounded-lg border p-4">
      <div className="space-y-2">
        <label className="block text-sm font-medium" htmlFor="reset-email">
          Email
        </label>
        <input
          id="reset-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          placeholder="you@example.com"
        />
      </div>
      <Button type="submit" disabled={submitting} className="w-full">
        {submitting ? "Please wait…" : "Send reset link"}
      </Button>
    </form>
  );
}
