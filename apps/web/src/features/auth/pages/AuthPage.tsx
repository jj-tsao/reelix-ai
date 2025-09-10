import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { updatePassword } from "../api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Link } from "react-router-dom";

export default function AuthPage() {
  const { lastEvent, user } = useAuth();
  const routerLoc = useLocation();
  const navigate = useNavigate();
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { toast } = useToast();

  const showingRecovery = useMemo(() => {
    const winHash = typeof window !== "undefined" ? window.location.hash : "";
    const hash = routerLoc.hash || winHash;
    const hParams = new URLSearchParams(
      hash.startsWith("#") ? hash.slice(1) : hash
    );
    const qParams = new URLSearchParams(
      typeof window !== "undefined" ? window.location.search : ""
    );
    return (
      hParams.get("type") === "recovery" ||
      qParams.get("type") === "recovery" ||
      lastEvent === "PASSWORD_RECOVERY"
    );
  }, [routerLoc.hash, lastEvent]);

  // If already signed in and not in recovery, send to Home for a cleaner flow
  useEffect(() => {
    if (user && !showingRecovery) {
      navigate("/", { replace: true });
    }
  }, [user, showingRecovery, navigate]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      {showingRecovery ? (
        <section className="mx-auto w-full max-w-md">
          <form
            className="space-y-4 rounded-lg border p-4"
            onSubmit={async (e) => {
              e.preventDefault();
              setSubmitting(true);
              const res = await updatePassword(newPassword);
              setSubmitting(false);
              if (!res.ok) {
                toast({
                  title: "Update failed",
                  description: res.error,
                  variant: "destructive",
                });
                return;
              }
              toast({
                title: "Password updated",
                description: "You can now sign in with your new password.",
                variant: "success",
              });
              setNewPassword("");
              if (typeof window !== "undefined") {
                history.replaceState(null, "", window.location.pathname);
              }
            }}
          >
            <h1 className="mb-3 text-xl md:text-2xl font-semibold tracking-tight text-center">Reset Password</h1>
            <p className="-mt-2 mb-2 text-sm text-muted-foreground text-center">Enter a new password for your account.</p>
            <div className="space-y-2">
              <label
                className="block text-sm font-medium"
                htmlFor="new-password"
              >
                New Password
              </label>
              <input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={6}
                className="w-full rounded-md border px-3 py-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                placeholder="••••••••"
              />
            </div>
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Please wait…" : "Update password"}
            </Button>
            <div className="text-center">
              <Button variant="link" asChild>
                <Link to="/">Back to Home</Link>
              </Button>
            </div>
          </form>
        </section>
      ) : (
        <section className="mx-auto w-full max-w-md">
          <div className="space-y-4 rounded-lg border p-4">
            <h1 className="mb-3 text-xl md:text-2xl font-semibold tracking-tight text-center">Account</h1>
            <p className="-mt-2 mb-2 text-sm text-muted-foreground text-center">
              Sign in or create a new account.
            </p>
            <div className="space-y-2">
              <Button className="w-full" asChild>
                <Link to="/auth/signin">Go to Sign In</Link>
              </Button>
              <Button variant="outline" className="w-full" asChild>
                <Link to="/auth/signup">Create Account</Link>
              </Button>
            </div>
            <div className="text-center">
              <Button variant="link" asChild>
                <Link to="/">Back to Home</Link>
              </Button>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
