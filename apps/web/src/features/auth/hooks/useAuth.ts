import { useEffect, useState } from "react";
import type { Session, User, AuthChangeEvent } from "@supabase/supabase-js";
import { getCurrentSession, onAuthStateChange } from "../api";

type AuthState = {
  user: User | null;
  session: Session | null;
  loading: boolean;
  lastEvent: AuthChangeEvent | null;
};

export function useAuth() {
  const [state, setState] = useState<AuthState>({ user: null, session: null, loading: true, lastEvent: null });

  async function refresh() {
    const session = await getCurrentSession();
    setState((s) => ({ ...s, session, user: session?.user ?? null, loading: false }));
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      const session = await getCurrentSession();
      if (!mounted) return;
      setState((s) => ({ ...s, session, user: session?.user ?? null, loading: false }));
    })();
    const unsubscribe = onAuthStateChange((event) => {
      setState((s) => ({ ...s, lastEvent: event }));
      refresh();
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  return state;
}
