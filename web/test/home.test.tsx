import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Home from "../src/app/page";
import { fetchCities } from "../src/lib/api";

const LAHORE = {
  slug: "lahore",
  name: "Lahore",
  center: { lat: 31.52, lng: 74.36 },
  defaultRadiusKm: 25,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("lists the cities from the API", async () => {
  vi.stubEnv("API_ORIGIN", "https://moviespk-api.vercel.app/");
  const fetchMock = stubFetch(Response.json({ data: [LAHORE], meta: {} }));
  render(await Home());
  expect(screen.getByRole("heading", { name: "MoviesPK" })).toBeTruthy();
  expect(screen.getByText("Lahore")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("https://moviespk-api.vercel.app/api/v1/cities", {
    next: { revalidate: 3600 },
  });
});

it("shows a fallback when the API fails", async () => {
  vi.stubEnv("API_ORIGIN", "https://moviespk-api.vercel.app");
  stubFetch(new Error("network down"));
  render(await Home());
  expect(screen.getByRole("status").textContent).toContain("not available");
});

it.each([
  ["no API_ORIGIN", undefined, Response.json({ data: [LAHORE] })],
  ["HTTP 500", "https://x.example", new Response("oops", { status: 500 })],
  ["malformed body", "https://x.example", Response.json({ data: [{ slug: 1 }] })],
])("fetchCities returns null on %s", async (_name, origin, response) => {
  if (origin === undefined) vi.stubEnv("API_ORIGIN", "");
  else vi.stubEnv("API_ORIGIN", origin);
  stubFetch(response);
  expect(await fetchCities()).toBeNull();
});
