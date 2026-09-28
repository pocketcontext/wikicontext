import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getPage,
  listPages,
  logout,
  pb,
  query,
  refreshSession,
  searchPages,
  TruncatedQueryError,
} from "./api";

const publication = "publication0001";
const user = {
  id: "user00000000001",
  collectionId: "_pb_users_auth_",
  collectionName: "users",
};
function response(rows: Record<string, unknown>[], truncated = false) {
  const columns = Object.keys(rows[0] ?? {});
  return {
    columns,
    rows: rows.map((row) => columns.map((column) => row[column])),
    truncated,
  };
}
const validManifest = () =>
  response([{ manifest_type: "object", total: 1, unique_keys: 1, invalid: 0 }]);

afterEach(() => {
  vi.restoreAllMocks();
  pb.authStore.clear();
});

describe("published knowledge reads", () => {
  it.each([
    { manifest_type: "array", total: 0, unique_keys: 0, invalid: 0 },
    { manifest_type: "object", total: 2, unique_keys: 1, invalid: 0 },
    { manifest_type: "object", total: 1, unique_keys: 1, invalid: 1 },
  ])(
    "rejects malformed or incomplete manifests before reading content: %j",
    async (check) => {
      const send = vi.spyOn(pb, "send").mockResolvedValue(response([check]));
      await expect(listPages(publication)).rejects.toThrow(
        "incomplete or invalid",
      );
      expect(send).toHaveBeenCalledTimes(1);
    },
  );

  it("returns no content for an unavailable publication", async () => {
    const send = vi.spyOn(pb, "send").mockResolvedValue(response([]));
    await expect(listPages(publication)).resolves.toEqual([]);
    await expect(searchPages(publication, "anything")).resolves.toEqual([]);
    await expect(getPage(publication, "missing")).resolves.toBeNull();
    expect(send).toHaveBeenCalledTimes(3);
  });

  it("rejects truncated results instead of presenting partial evidence", async () => {
    vi.spyOn(pb, "send").mockResolvedValue(response([{ id: "partial" }], true));
    await expect(query("SELECT id FROM pages")).rejects.toBeInstanceOf(
      TruncatedQueryError,
    );
  });

  it("pins index reads to the manifest and excludes archived and staged revisions", async () => {
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockResolvedValue(response([]));
    await listPages(publication);
    const sql = send.mock.calls[1][1]?.body.sql as string;
    expect(sql).toContain("pub.id='publication0001'");
    expect(sql).toContain("JOIN json_each(pub.manifest) m");
    expect(sql).toContain("p.id=m.key");
    expect(sql).toContain("r.id=m.value");
    expect(sql).toContain("m.type='text'");
    expect(sql).toContain("r.page=p.id");
    expect(sql).toContain("r.archived=0");
    expect(sql).not.toContain("pub.manifest, pub");
  });

  it("retries truncated index pages at a smaller size without skipping rows", async () => {
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockResolvedValueOnce(response([{ id: "partial" }], true))
      .mockResolvedValueOnce(response([{ id: "complete" }]));
    await expect(listPages(publication)).resolves.toEqual([{ id: "complete" }]);
    expect(send.mock.calls[1][1]?.body.sql).toContain("LIMIT 100 OFFSET 0");
    expect(send.mock.calls[2][1]?.body.sql).toContain("LIMIT 50 OFFSET 0");
  });

  it("reduces pages when the server rejects the response byte budget", async () => {
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockRejectedValueOnce({ status: 413 })
      .mockResolvedValueOnce(response([]));
    await expect(listPages(publication)).resolves.toEqual([]);
    expect(send.mock.calls[2][1]?.body.sql).toContain("LIMIT 50 OFFSET 0");
  });

  it("rejects invalid IDs, slugs and pagination before sending requests", async () => {
    const send = vi.spyOn(pb, "send");
    await expect(listPages("' OR 1=1")).rejects.toThrow("identity");
    await expect(getPage(publication, "../draft")).rejects.toThrow("slug");
    await expect(searchPages(publication, "hi", -1)).rejects.toThrow(
      "query page",
    );
    expect(send).not.toHaveBeenCalled();
  });

  it("quotes search terms and keeps searches within a pinned publication", async () => {
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockResolvedValue(response([]));
    await searchPages(publication, "O'Brien %", 50, 50);
    const sql = send.mock.calls[1][1]?.body.sql as string;
    expect(sql).toContain("lower('O''Brien')");
    expect(sql).toContain("lower('%')");
    expect(sql).toContain("pub.id='publication0001'");
    expect(sql).toContain("LIMIT 50 OFFSET 50");
  });

  it("returns missing pages without querying draft evidence", async () => {
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockResolvedValue(response([]));
    await expect(getPage(publication, "missing")).resolves.toBeNull();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("loads citations only for the selected revision and pins both link directions", async () => {
    const page = {
      id: "revision0000001",
      page: "page00000000001",
      slug: "example",
      title: "Example",
      summary: "",
      kind: "concept",
      body: "Text[^1]",
    };
    const send = vi
      .spyOn(pb, "send")
      .mockResolvedValueOnce(validManifest())
      .mockResolvedValueOnce(response([page]))
      .mockResolvedValue(response([]));
    await expect(getPage(publication, "example")).resolves.toEqual({
      ...page,
      citations: [],
      backlinks: [],
      links: [],
    });
    const sql = send.mock.calls
      .slice(1)
      .map((call) => call[1]?.body.sql as string);
    expect(sql[1]).toContain("c.page_revision='revision0000001'");
    for (const linkQuery of sql.slice(2)) {
      expect(linkQuery).toContain("pub.id='publication0001'");
      expect(linkQuery).toContain("r.archived=0");
    }
  });

  it.each([401, 403])(
    "clears a revoked session after SQL status %i",
    async (status) => {
      pb.authStore.save("expired", {
        id: "user00000000001",
        collectionId: "_pb_users_auth_",
        collectionName: "users",
      });
      vi.spyOn(pb, "send").mockRejectedValue({ status });
      await expect(query("SELECT id FROM pages")).rejects.toEqual({ status });
      expect(pb.authStore.token).toBe("");
      expect(
        window.sessionStorage.getItem("wikicontext.reader.auth"),
      ).toBeNull();
    },
  );

  it.each([false, true])(
    "does not restore an old refresh after logout (new login: %s)",
    async (loginAgain) => {
      pb.authStore.save("old-token", user);
      let resolve!: (value: unknown) => void;
      vi.spyOn(pb, "send").mockImplementation(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
      const refresh = refreshSession();
      logout();
      if (loginAgain) pb.authStore.save("new-login-token", user);
      resolve({ token: "refreshed-old-token", record: user });
      await refresh;
      expect(pb.authStore.token).toBe(loginAgain ? "new-login-token" : "");
    },
  );

  it("does not revoke a new session when an old request returns unauthorized", async () => {
    pb.authStore.save("old-token", user);
    let reject!: (reason: unknown) => void;
    vi.spyOn(pb, "send").mockImplementation(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    );
    const pending = query("SELECT id FROM pages");
    pb.authStore.save("new-login-token", user);
    reject({ status: 401 });
    await expect(pending).rejects.toEqual({ status: 401 });
    expect(pb.authStore.token).toBe("new-login-token");
  });
});
