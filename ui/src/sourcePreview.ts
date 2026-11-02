import { api, pb, sessionGeneration } from "./api";
import type { Source } from "./types";

export const SOURCE_PREVIEW_BYTES = 2 * 1024 * 1024;
export class SourcePreviewLimitError extends Error {
  constructor(limit = SOURCE_PREVIEW_BYTES) {
    super(
      `This original is larger than the ${limit / (1024 * 1024)} MiB reading limit. Download it or read its passages.`,
    );
  }
}
/** Read the independently authorized original, never an approximation assembled from passages. */
async function sourceBytes(
  source: Source,
  signal?: AbortSignal,
  limit = SOURCE_PREVIEW_BYTES,
): Promise<Uint8Array<ArrayBuffer>> {
  if (!/^[a-z0-9]{15}$/.test(source.id))
    throw new Error("Invalid source identity");
  const generation = sessionGeneration;
  const token = pb.authStore.token;
  const controller = new AbortController();
  const combined = signal
    ? AbortSignal.any([signal, controller.signal])
    : controller.signal;
  const current = () => {
    combined.throwIfAborted();
    if (
      generation !== sessionGeneration ||
      token !== pb.authStore.token ||
      !pb.authStore.isValid
    )
      throw new Error("Session changed");
  };
  const unsubscribe = pb.authStore.onChange(() => {
    if (
      generation !== sessionGeneration ||
      token !== pb.authStore.token ||
      !pb.authStore.isValid
    )
      controller.abort();
  });
  try {
    current();
    const url = await api.originalURL(source);
    current();
    if (new URL(url).origin !== new URL(pb.baseURL).origin)
      throw new Error("Invalid original location");
    const response = await fetch(url, {
      signal: combined,
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
    });
    current();
    if (!response.ok) {
      if (
        (response.status === 401 || response.status === 403) &&
        token === pb.authStore.token
      )
        pb.authStore.clear();
      throw new Error("This original is unavailable or access was denied.");
    }
    if (Number(response.headers.get("content-length")) > limit) {
      await response.body?.cancel();
      throw new SourcePreviewLimitError(limit);
    }
    if (!response.body)
      throw new Error("This original has no readable content.");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0,
      complete = false;
    try {
      for (;;) {
        const chunk = await reader.read();
        current();
        if (chunk.done) {
          complete = true;
          break;
        }
        size += chunk.value.byteLength;
        if (size > limit) throw new SourcePreviewLimitError(limit);
        chunks.push(chunk.value);
      }
    } finally {
      if (!complete) await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    if (!crypto.subtle || !/^[a-f0-9]{64}$/.test(source.sha256))
      throw new Error("The original cannot be verified. Download it instead.");
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    current();
    const hash = Array.from(digest, (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (hash !== source.sha256)
      throw new Error("The original does not match its recorded checksum.");
    return bytes;
  } finally {
    unsubscribe();
  }
}

export async function sourceText(
  source: Source,
  signal?: AbortSignal,
): Promise<string> {
  const bytes = await sourceBytes(source, signal);
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(
      "This original is not valid UTF-8 text. Download it instead.",
    );
  }
}
