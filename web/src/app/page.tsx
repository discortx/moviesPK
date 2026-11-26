import { fetchCities } from "../lib/api";

// ISR: rebuilt at most hourly, the same as the API's edge cache for /cities (plan §9.3).
export const revalidate = 3600;

/** Placeholder home page (plan P1-16): proves web → API works end to end. */
export default async function Home() {
  const cities = await fetchCities();
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-4">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">MoviesPK</h1>
        <p className="text-lg">Movies playing at cinemas near you in Pakistan. Coming soon.</p>
      </header>
      <section aria-labelledby="cities-heading" className="flex flex-col gap-2">
        <h2 id="cities-heading" className="text-xl font-medium">
          Cities
        </h2>
        {cities === null ? (
          <p role="status">The city list is not available right now.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {cities.map((city) => (
              <li key={city.slug} className="rounded-full border px-3 py-1">
                {city.name}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
