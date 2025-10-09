import { Link } from "react-router-dom";

export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-[70vh] w-full max-w-4xl flex-col items-center justify-center px-6 text-center">
      <h1 className="text-4xl font-semibold tracking-tight text-foreground">
        Welcome to Reelix
      </h1>
      <p className="mt-4 max-w-2xl text-base text-muted-foreground">
        We&apos;re crafting a new landing experience. In the meantime, you can head to
        the query-based discovery page to explore recommendations tailored to your vibe.
      </p>
      <Link
        to="/query"
        className="mt-6 inline-flex items-center rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90"
      >
        Explore recommendations
      </Link>
    </main>
  );
}
