import { useEffect, useState } from "react";
import { getAppUser } from "../api";

export function useProfile(userId?: string | null) {
  // Initialize from localStorage to avoid UI flicker
  const initial = (() => {
    try {
      if (!userId) return null;
      return localStorage.getItem(`profileDisplayName:${userId}`);
    } catch (e) {
      void e; // no-op
      return null;
    }
  })();
  const [displayName, setDisplayName] = useState<string | null>(initial);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      if (!userId) {
        setDisplayName(null);
        return;
      }
      setLoading(true);
      const row = await getAppUser(userId);
      if (!active) return;
      const name = row?.display_name ?? null;
      setDisplayName(name);
      try {
        if (name) localStorage.setItem(`profileDisplayName:${userId}`, name);
      } catch (e) {
        void e; // no-op
      }
      setLoading(false);
    }
    load();
    return () => {
      active = false;
    };
  }, [userId]);

  return { displayName, loading } as const;
}
