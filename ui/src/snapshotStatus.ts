/** Requester snapshot metadata only; never stores rows or credentials. */
export interface SnapshotStatus {
  generation: string;
  capturedAt: string;
  refreshing: boolean;
  stale: boolean;
  rows: number;
  diskBytes: number;
  lastError?: string;
}

type Listener = (status: SnapshotStatus | null, changed: boolean) => void;

export function snapshotStatus(value: unknown): SnapshotStatus {
  if (!value || typeof value !== "object") throw new Error("Invalid snapshot status");
  const status = { generation: "", capturedAt: "", refreshing: false, stale: false,
    rows: 0, diskBytes: 0, ...value } as SnapshotStatus;
  if (typeof status.generation !== "string" || status.generation.length > 512 ||
      typeof status.capturedAt !== "string" || status.capturedAt.length > 64 ||
      typeof status.refreshing !== "boolean" || typeof status.stale !== "boolean" ||
      !Number.isSafeInteger(status.rows) || status.rows < 0 ||
      !Number.isSafeInteger(status.diskBytes) || status.diskBytes < 0 ||
      (status.lastError !== undefined && typeof status.lastError !== "string"))
    throw new Error("Invalid snapshot status");
  return status;
}

export class SnapshotMonitor {
  current: SnapshotStatus | null = null;
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private pending: Promise<SnapshotStatus> | undefined;
  private epoch = 0;

  constructor(private read: () => Promise<SnapshotStatus>) {}

  get watching() { return this.listeners.size > 0; }

  reset() {
    this.epoch++;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = undefined;
    this.current = null;
    for (const listener of this.listeners) listener(null, false);
  }

  observe(status: SnapshotStatus) {
    // Parallel queries can finish out of order. Do not regress a completed
    // generation or lose a newer refresh status to an older response.
    if (this.current?.generation && status.generation &&
        Date.parse(status.capturedAt) < Date.parse(this.current.capturedAt)) return;
    const changed = this.current !== null && !!status.generation && status.generation !== this.current.generation;
    this.current = status;
    for (const listener of this.listeners) listener(status, changed);
    this.schedule();
  }

  watch(listener: Listener) {
    this.listeners.add(listener);
    listener(this.current, false);
    this.schedule();
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        clearTimeout(this.timer);
        this.timer = undefined;
      }
    };
  }

  refresh(): Promise<SnapshotStatus> {
    if (this.pending) return this.pending;
    const epoch = this.epoch;
    const request = this.read().then(status => {
      if (epoch !== this.epoch) throw new Error("Reader session changed");
      this.observe(status);
      return status;
    }).finally(() => {
      if (this.pending === request) this.pending = undefined;
      if (epoch === this.epoch) this.schedule();
    });
    this.pending = request;
    return request;
  }

  private schedule() {
    if (this.timer || !this.listeners.size ||
        (!this.current?.refreshing && !this.current?.stale)) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.refresh().catch(() => { this.schedule(); });
    }, 1000);
  }
}
