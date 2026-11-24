import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Home from "../src/app/page";

it("renders the MoviesPK heading", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { name: "MoviesPK" })).toBeTruthy();
});
