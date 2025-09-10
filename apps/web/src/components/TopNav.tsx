import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { signOut } from "@/features/auth/api";

export default function TopNav() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();

  async function handleSignOut() {
    const res = await signOut();
    if (!res.ok) {
      toast({ title: "Sign out failed", description: res.error, variant: "destructive" });
      return;
    }
    toast({ title: "Signed out", description: "See you soon!", variant: "success" });
    navigate("/");
  }
  return (
    <header className="sticky top-0 z-50 w-full flex items-center justify-between px-1 sm:px-4 lg:px-6 py-3 sm:py-4 lg:py-4 border-b border-border bg-background/80 backdrop-blur-md">
      <Link to="/" className="flex items-center space-x-3">
        <img
          src="/logo/Reelix_logo_dark.svg"
          alt="Reelix"
          className="h-10 w-auto"
        />
      </Link>
      <div className="flex items-center gap-3">
        {!loading && user ? (
          <>
            <span className="hidden text-sm sm:inline text-muted-foreground">
              {user.email}
            </span>
            <Button size="sm" variant="outline" onClick={handleSignOut}>
              Sign out
            </Button>
          </>
        ) : (
          <Button size="sm" asChild>
            <Link to="/auth/signin">Sign In</Link>
          </Button>
        )}
      </div>
    </header>
  );
}
