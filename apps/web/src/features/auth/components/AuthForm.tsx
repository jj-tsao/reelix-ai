import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { signInWithPassword, signUpWithPassword } from "../api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

type Mode = "signin" | "signup";

export default function AuthForm() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setSubmitting(true);
    try {
      if (mode === "signin") {
        const res = await signInWithPassword(email, password);
        if (!res.ok) return setError(res.error);
        navigate("/");
      } else {
        const res = await signUpWithPassword(email, password);
        if (!res.ok) return setError(res.error);
        setInfo("Signed up! Check your email to confirm.");
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
            error={error}
            info={info}
          />
        </TabsContent>
        <TabsContent value="signup">
          <AuthFields
            email={email}
            password={password}
            setEmail={setEmail}
            setPassword={setPassword}
            onSubmit={onSubmit}
            submitting={submitting}
            cta="Create Account"
            error={error}
            info={info}
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
  onSubmit: (e: React.FormEvent) => void;
  submitting: boolean;
  cta: string;
  error: string | null;
  info: string | null;
}) {
  const { email, password, setEmail, setPassword, onSubmit, submitting, cta, error, info } = props;
  return (
    <form onSubmit={onSubmit} className="mt-4 space-y-4 rounded-lg border p-4">
      {error ? (
        <div className="text-sm text-red-600">{error}</div>
      ) : info ? (
        <div className="text-sm text-green-600">{info}</div>
      ) : null}
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
        {submitting ? "Please wait…" : cta}
      </Button>
    </form>
  );
}

