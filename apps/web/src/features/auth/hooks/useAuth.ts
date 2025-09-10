import { useEffect, useState } from "react";
import type { Session, User, AuthChangeEvent } from "@supabase/supabase-js";
import { getAppUser, getCurrentSession, onAuthStateChange, upsertAppUser } from "../api";

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

  // On first authenticated load, if we have a pending display name from sign up,
  // upsert the app_user profile and clear the pending value.
  useEffect(() => {
    (async () => {
      if (!state.user || state.loading) return;
      try {
        const pending = localStorage.getItem("pendingDisplayName");
        if (!pending) return;
        const existing = await getAppUser(state.user.id);
        if (!existing || !existing.display_name) {
          await upsertAppUser({
            user_id: state.user.id,
            email: state.user.email || "",
            display_name: pending,
          });
        }
        try {
          localStorage.setItem(`profileDisplayName:${state.user.id}`, pending);
        } catch {}
        localStorage.removeItem("pendingDisplayName");
      } catch {
        // ignore
      }
    })();
  }, [state.user?.id, state.loading]);

  return state;
}
