import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "./supabase";

let bootstrapPromise: Promise<Session | null> | null = null;
let listenerInitialized = false;

function initAuthListener() {
  if (listenerInitialized) return;
  listenerInitialized = true;
  supabase.auth.onAuthStateChange((event) => {
    if (event === "SIGNED_OUT" || event === "USER_DELETED") {
      // After a full sign out, fall back to an anonymous session.
      void ensureSupabaseSession();
    }
  });
}

async function fetchExistingSession(): Promise<Session | null> {
  try {
    const { data, error } = await supabase.auth.getSession();
    if (error) {
      console.warn("Failed to read Supabase session", error);
      return null;
    }
    return data.session ?? null;
  } catch (error) {
    console.warn("Unexpected Supabase session error", error);
    return null;
  }
}

async function signInAnonymously(): Promise<Session | null> {
  try {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) {
      console.warn("Supabase anonymous sign-in failed", error);
      return null;
    }
    return data.session ?? null;
  } catch (error) {
    console.warn("Unexpected anonymous sign-in error", error);
    return null;
  }
}

export async function ensureSupabaseSession(): Promise<Session | null> {
  initAuthListener();
  const existing = await fetchExistingSession();
  if (existing) return existing;

  if (!bootstrapPromise) {
    bootstrapPromise = (async () => {
      const session = await signInAnonymously();
      if (session) return session;
      return fetchExistingSession();
    })();
  }

  try {
    return await bootstrapPromise;
  } finally {
    bootstrapPromise = null;
  }
}

export async function getSupabaseAccessToken(): Promise<string | null> {
  const session = await ensureSupabaseSession();
  return session?.access_token ?? null;
}

export function isAnonymousUser(user: User | null | undefined): boolean {
  if (!user) return false;
  if (typeof user.is_anonymous === "boolean") return user.is_anonymous;
  const provider = user.app_metadata?.provider;
  return typeof provider === "string" && provider === "anonymous";
}
