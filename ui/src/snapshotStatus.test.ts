import { afterEach, describe, expect, it, vi } from "vitest";
import { SnapshotMonitor, snapshotStatus, type SnapshotStatus } from "./snapshotStatus";

const status = (generation: string, extra: Partial<SnapshotStatus> = {}): SnapshotStatus => ({
  generation, capturedAt: "2026-10-23T10:00:00Z", refreshing: false, stale: false,
  rows: 10, diskBytes: 4096, ...extra,
});
afterEach(() => vi.useRealTimers());

describe("snapshot refresh notifications", () => {
  it("polls a stale generation and announces the replacement without another publication event", async () => {
    vi.useFakeTimers();
    const read = vi.fn().mockResolvedValue(status("new", { capturedAt: "2026-10-23T10:00:01Z" }));
    const monitor = new SnapshotMonitor(read);
    const changed: string[] = [];
    const stop = monitor.watch((value, change) => { if (change) changed.push(value!.generation); });
    monitor.observe(status("old", { stale: true, refreshing: true }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(changed).toEqual(["new"]);
    await vi.advanceTimersByTimeAsync(5000);
    expect(read).toHaveBeenCalledTimes(1);
    stop();
  });

  it("does not regress to a slower response from an older generation", () => {
    const monitor = new SnapshotMonitor(vi.fn());
    monitor.observe(status("new", { capturedAt: "2026-10-23T10:01:00Z" }));
    monitor.observe(status("old"));
    expect(monitor.current?.generation).toBe("new");
  });

  it("fences an in-flight status read when the identity changes", async () => {
    let resolve!: (value: SnapshotStatus) => void;
    const monitor = new SnapshotMonitor(() => new Promise(done => { resolve = done; }));
    const pending = monitor.refresh();
    monitor.reset();
    resolve(status("previous-user"));
    await expect(pending).rejects.toThrow("session changed");
    expect(monitor.current).toBeNull();
  });

  it("stops background polling when the view closes", async () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const monitor = new SnapshotMonitor(read);
    const stop = monitor.watch(() => {});
    monitor.observe(status("old", { stale: true }));
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(read).not.toHaveBeenCalled();
  });

  it("rejects malformed metadata instead of marking a generation complete", () => {
    expect(() => snapshotStatus({ ...status("x"), rows: -1 })).toThrow("Invalid snapshot status");
  });
});
