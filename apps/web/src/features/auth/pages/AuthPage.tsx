import AuthForm from "../components/AuthForm";

export default function AuthPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="mb-4 text-2xl font-semibold">Personalize Your Discovery.</h1>
      <p className="mb-6 text-sm text-muted-foreground">Sign in or create your account to unlock personalized discovery.</p>
      <AuthForm />
    </main>
  );
}

