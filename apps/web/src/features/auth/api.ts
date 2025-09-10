import { supabase } from "@/lib/supabase";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";
import type { Tables } from "@/types/supabase";

export type AuthResult = { ok: true } | { ok: false; error: string };

export async function signUpWithPassword(
  email: string,
  password: string,
  displayName?: string
): Promise<AuthResult> {
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo:
        typeof window !== "undefined" ? `${window.location.origin}` : undefined,
      data: displayName ? { display_name: displayName } : undefined,
    },
  });
  if (error) return { ok: false, error: error.message };

  // Supabase nuance: if the email is already registered, signUp returns
  // data.user.identities = [] and no email is sent. Treat as an error so
  // the UI can prompt the user to sign in or reset password.
  const identitiesLen = data?.user?.identities?.length ?? 0;
  if (identitiesLen === 0) {
    return {
      ok: false,
      error: "This email is already registered. Try signing in or resetting your password.",
    };
  }

  return { ok: true };
}

export async function signInWithPassword(email: string, password: string): Promise<AuthResult> {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}

export async function signOut(): Promise<AuthResult> {
  const { error } = await supabase.auth.signOut();
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}

export async function getCurrentSession() {
  const { data } = await supabase.auth.getSession();
  return data.session ?? null;
}

export function onAuthStateChange(callback: (event: AuthChangeEvent, session: Session | null) => void) {
  const { data } = supabase.auth.onAuthStateChange((event, session) => callback(event, session));
  return () => data.subscription.unsubscribe();
}

export async function requestPasswordReset(email: string, redirectTo?: string): Promise<AuthResult> {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: redirectTo ?? (typeof window !== "undefined" ? `${window.location.origin}/auth` : undefined),
  });
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}

export async function updatePassword(newPassword: string): Promise<AuthResult> {
  const { error } = await supabase.auth.updateUser({ password: newPassword });
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}

// Profiles (app_user)
export async function getAppUser(userId: string) {
  const { data, error } = await supabase
    .from("app_user")
    .select("user_id, email, display_name")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) return null;
  return data as Pick<Tables<"app_user">, "user_id" | "email" | "display_name"> | null;
}

export async function upsertAppUser(row: Partial<Tables<"app_user">>) {
  const { error } = await supabase
    .from("app_user")
    .upsert(row, { onConflict: "user_id" });
  if (error) return { ok: false as const, error: error.message };
  return { ok: true as const };
}
