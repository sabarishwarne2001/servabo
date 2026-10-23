/** A workspace with no logo of its own shows the Servabo logo, never initials or an empty badge. */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const image = vi.hoisted(() => ({ src: null as string | null }));
vi.mock("@/hooks/useAuthenticatedImage", () => ({ useAuthenticatedImage: () => image.src, forgetBrokenImage: vi.fn() }));

import { ServaboMark } from "./ServaboMark";
import { WorkspaceLogo } from "@/components/workspace/WorkspaceLogo";

afterEach(cleanup);

const workspace = { id: "w1", workspace_name: "Acme Books", company_logo_url: null };

describe("the default workspace logo", () => {
  it("shows the Servabo logo when the workspace has not uploaded one", () => {
    image.src = null;
    const { container } = render(<WorkspaceLogo workspace={workspace} />);
    expect(container.querySelector("svg[data-servabo-mark]")).not.toBeNull();
    expect(screen.queryByText("AB")).toBeNull();
    expect(screen.getByRole("img", { name: /Acme Books/ })).toBeTruthy();
  });

  it("shows the workspace's own logo when there is one", () => {
    image.src = "blob:logo";
    const { container } = render(<WorkspaceLogo workspace={{ ...workspace, company_logo_url: "/x" }} />);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:logo");
    expect(container.querySelector("svg[data-servabo-mark]")).toBeNull();
  });

  it("falls back to the Servabo logo when the workspace's logo cannot be loaded", async () => {
    image.src = "blob:broken";
    const { container } = render(<WorkspaceLogo workspace={{ ...workspace, company_logo_url: "/x" }} />);
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(await screen.findByRole("img", { name: /Servabo logo/ })).toBeTruthy();
  });
});

describe("the mark", () => {
  it("is decorative unless it is given a name", () => {
    const { container } = render(<ServaboMark />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("gives every drawing its own gradient ids, so a hidden copy cannot take the paint with it", () => {
    const { container } = render(
      <>
        <ServaboMark />
        <ServaboMark />
      </>,
    );
    const ids = [...container.querySelectorAll("linearGradient, radialGradient")].map((n) => n.id);
    expect(ids.length).toBe(8);
    expect(new Set(ids).size).toBe(8);
  });
});
