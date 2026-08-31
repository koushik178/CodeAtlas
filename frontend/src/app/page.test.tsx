import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

const repositories = [
  {
    id: 1,
    owner: "openai",
    name: "codex",
    full_name: "openai/codex",
    github_url: "https://github.com/openai/codex",
    description: "Developer agent tools",
    language: "TypeScript",
    default_branch: "main",
    stars: 10,
    forks: 2,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: 2,
    owner: "example",
    name: "api-service",
    full_name: "example/api-service",
    github_url: "https://github.com/example/api-service",
    description: "Python service for repository analysis",
    language: "Python",
    default_branch: "main",
    stars: 3,
    forks: 1,
    created_at: "2026-01-02T00:00:00Z",
  },
];

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.endsWith("/health")) return Promise.resolve(jsonResponse({ status: "healthy" }));
    if (url.endsWith("/api/repositories")) return Promise.resolve(jsonResponse(repositories));
    if (url.endsWith("/files")) return Promise.resolve(jsonResponse({ repository_id: 2, files: [] }));
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  }));
});

describe("CodeAtlas repository dashboard", () => {
  it("filters already-fetched repositories without another API call", async () => {
    const user = userEvent.setup();
    render(<Home />);

    await screen.findByText("openai/codex");
    const fetchMock = vi.mocked(fetch);
    const initialCalls = fetchMock.mock.calls.length;
    await user.type(screen.getByRole("searchbox", { name: "Search imported repositories" }), "python");

    expect(screen.getByText("example/api-service")).toBeDefined();
    expect(screen.queryByText("openai/codex")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(initialCalls);
  });

  it("opens a selected repository and retains existing repository features", async () => {
    const user = userEvent.setup();
    render(<Home />);

    await screen.findByText("example/api-service");
    await user.click(screen.getAllByRole("button", { name: "Open" })[1]);

    expect(await screen.findByText("Selected repository")).toBeDefined();
    expect(screen.getByRole("heading", { name: "Ask about this repository" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Automated code review" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Unit-test generation" })).toBeDefined();
  });
});
