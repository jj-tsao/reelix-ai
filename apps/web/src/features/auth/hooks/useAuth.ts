import { useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { getCurrentSession, onAuthStateChange } from "../api";

type AuthState = {
  user: User | null;
  session: Session | null;
  loading: boolean;
};

export function useAuth() {
  const [state, setState] = useState<AuthState>({ user: null, session: null, loading: true });

  async function refresh() {
    const session = await getCurrentSession();
    setState({ session, user: session?.user ?? null, loading: false });
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      const session = await getCurrentSession();
      if (!mounted) return;
      setState({ session, user: session?.user ?? null, loading: false });
    })();
    const unsubscribe = onAuthStateChange(() => {
      refresh();
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  return state;
}

