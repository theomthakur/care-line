import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Overview } from "./pages/Overview";
import { DEMO_CASES } from "./fixtures";
import { summaryFromState } from "./derive";

afterEach(cleanup);

it("keeps an unverified member name out of the overview and conversation directory", () => {
  const call = summaryFromState(DEMO_CASES[0]);
  render(
    <Overview
      calls={[
        {
          ...call,
          verification: "unverified",
          member: { ...call.member!, name: "Private member name" },
        },
      ]}
      loading={false}
      onOpen={vi.fn()}
      onNavigate={vi.fn()}
    />,
  );
  expect(screen.queryByText("Private member name")).toBeNull();
  expect(
    screen.queryByRole("button", { name: /Private member name/ }),
  ).toBeNull();
  expect(
    screen.getByRole("region", { name: "Conversation directory" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Open unverified caller conversation" }),
  ).toBeTruthy();
});
