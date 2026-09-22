import { afterEach, describe, expect, it, vi } from "vitest";

import { presentExternalFallback, renderContinueNotice } from "../src/content.js";

describe("content.js user-gesture routing (P1)", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("renders a clickable Continue control and does not route until it is clicked", async () => {
    const send = vi.fn(async () => ({ routed: true }));
    const assign = vi.fn();
    const notice = vi.fn();

    const promise = presentExternalFallback({
      externalLink: "https://jobs.example.com/apply/42",
      send,
      assign,
      notice,
    });

    expect(send).not.toHaveBeenCalled();
    const button = document.querySelector("#am-notice button");
    expect(button.textContent).toContain("jobs.example.com");

    button.click();
    await promise;

    expect(send).toHaveBeenCalledWith({
      type: "ROUTE_EXTERNAL",
      url: "https://jobs.example.com/apply/42",
    });
    expect(assign).toHaveBeenCalledWith("https://jobs.example.com/apply/42");
  });

  it("shows a notice and routes nothing when there is no external link", async () => {
    const send = vi.fn();
    const notice = vi.fn();

    const result = await presentExternalFallback({ externalLink: null, send, notice });

    expect(result.routed).toBe(false);
    expect(notice).toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("renders page-derived hosts as text, not markup", () => {
    renderContinueNotice("https://jobs.example.com/apply/42", () => {});
    const notice = document.getElementById("am-notice");
    expect(notice.querySelector("img")).toBeNull();
    expect(notice.textContent).toContain("jobs.example.com");
  });
});
