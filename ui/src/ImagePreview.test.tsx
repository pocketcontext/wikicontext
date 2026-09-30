import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, pb, previewURL } from "./api";
import ImagePreview from "./ImagePreview";
import type { Source } from "./types";

const source: Source = { id: "source000000001", title: "Synthetic slide", original_name: "slide.png", original: "slide.png", media_type: "image/png", source_date: "", sha256: "synthetic" };
const user = { id: "user00000000001", collectionName: "users", collectionId: "_pb_users_auth_" };
const auth = () => pb.authStore.save(`a.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }))}.c`, user);
beforeEach(auth);
afterEach(() => { cleanup(); vi.restoreAllMocks(); pb.authStore.clear(); });

it("uses an authenticated inline URL without turning the download URL into a preview", async () => {
  vi.spyOn(pb.files, "getToken").mockResolvedValue("protected-token");
  const inline = new URL(await previewURL(source));
  expect(inline.origin).toBe(window.location.origin);
  expect(inline.searchParams.get("token")).toBe("protected-token");
  expect(inline.searchParams.has("download")).toBe(false);
  expect(new URL(await api.originalURL(source)).searchParams.get("download")).toBe("true");
});

it("rejects a file token returned after logout", async () => {
  let finish!: (value: string) => void;
  vi.spyOn(pb.files, "getToken").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const pending = previewURL(source);
  pb.authStore.clear();
  finish("stale");
  await expect(pending).rejects.toThrow("Session changed");
});

it("never requests unsupported images or non-image sources", async () => {
  const request = vi.spyOn(api, "previewURL");
  const { rerender } = render(<ImagePreview source={{ ...source, media_type: "image/svg+xml" }} />);
  expect(screen.getByText(/Preview is unavailable/)).toBeVisible();
  await expect(previewURL({ ...source, media_type: "image/svg+xml" })).rejects.toThrow("Image preview unavailable");
  rerender(<ImagePreview source={{ ...source, media_type: "text/plain" }} />);
  expect(screen.queryByText(/Preview is unavailable/)).not.toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
});

it("retries failed images with a fresh protected URL", async () => {
  const request = vi.spyOn(api, "previewURL").mockResolvedValueOnce("/api/files/first").mockResolvedValueOnce("/api/files/retry");
  render(<ImagePreview source={source} />);
  const image = await screen.findByAltText("Original source: Synthetic slide");
  expect(screen.getByRole("status")).toHaveTextContent("Loading image preview");
  fireEvent.error(image);
  expect(screen.getByRole("alert")).toHaveTextContent("Unable to load image preview.");
  fireEvent.click(screen.getByRole("button", { name: "Retry image preview" }));
  await waitFor(() => expect(screen.getByAltText("Original source: Synthetic slide")).toHaveAttribute("src", "/api/files/retry"));
  fireEvent.load(screen.getByAltText("Original source: Synthetic slide"));
  expect(screen.getByRole("button", { name: "Enlarge image" })).toBeVisible();
  expect(request).toHaveBeenCalledTimes(2);
});

it("discards an old source response and clears the loaded preview on account changes", async () => {
  let finish!: (value: string) => void;
  vi.spyOn(api, "previewURL").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue("/api/files/current");
  const { rerender } = render(<ImagePreview source={source} />);
  rerender(<ImagePreview source={{ ...source, id: "source000000002", title: "Current slide" }} />);
  await screen.findByAltText("Original source: Current slide");
  await act(async () => finish("/api/files/stale"));
  expect(screen.queryByAltText("Original source: Synthetic slide")).not.toBeInTheDocument();
  expect(screen.getByAltText("Original source: Current slide")).toHaveAttribute("src", "/api/files/current");
  act(() => pb.authStore.clear());
  expect(screen.queryByAltText("Original source: Current slide")).not.toBeInTheDocument();
});
