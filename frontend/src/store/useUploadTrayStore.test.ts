/**
 * Final session 2A (Phase 4): the global upload tray takes a zip the way the Documents page does (spec 118): the zip goes
 * up whole through the archive upload and becomes its own batch, which the server unpacks; it is never sent as a
 * resumable document upload, and it is not listed in the tray's file batch.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  uploadArchive: vi.fn(async () => ({ id: "batch-zip-1" })),
  uploadFileResumable: vi.fn(async () => ({ workItemId: "wi-1" })),
  createBatch: vi.fn(async (_ws: string, files: { client_key: string; filename: string }[]) => ({
    id: "batch-files-1",
    items: files.map((f, i) => ({ id: `item-${i}`, client_key: f.client_key })),
  })),
  abortUploadSession: vi.fn(),
}));
vi.mock("@/services/api/ingestion", () => api);

import { useUploadTrayStore } from "./useUploadTrayStore";

const settle = async (): Promise<void> => {
  for (let i = 0; i < 40; i += 1) {
    if (!useUploadTrayStore.getState().files.some((f) => f.status === "queued" || f.status === "uploading")) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 60));
  }
};

describe("the global upload tray and zips", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUploadTrayStore.setState({ files: [], batchId: null, workspaceId: null, isOpen: false });
  });

  it("sends a zip through the archive upload and keeps its batch to show its documents", async () => {
    const zip = new File([new Uint8Array([80, 75, 3, 4])], "backlog.zip", { type: "application/zip" });
    await useUploadTrayStore.getState().enqueue("ws-1", [zip]);
    await settle();
    expect(api.uploadArchive).toHaveBeenCalledWith("ws-1", zip);
    expect(api.uploadFileResumable).not.toHaveBeenCalled();
    expect(api.createBatch).not.toHaveBeenCalled();
    const [row] = useUploadTrayStore.getState().files;
    expect(row).toMatchObject({ name: "backlog.zip", status: "done", archiveBatchId: "batch-zip-1" });
  });

  it("uploads ordinary files as before beside a zip, and lists only them in its batch", async () => {
    const zip = new File(["PK"], "more.ZIP");
    const pdf = new File(["%PDF-1.4"], "invoice.pdf", { type: "application/pdf" });
    await useUploadTrayStore.getState().enqueue("ws-1", [zip, pdf]);
    await settle();
    expect(api.createBatch).toHaveBeenCalledTimes(1);
    expect(api.createBatch.mock.calls[0]?.[1].map((f: { filename: string }) => f.filename)).toEqual(["invoice.pdf"]);
    expect(api.uploadFileResumable).toHaveBeenCalledTimes(1);
    expect(api.uploadArchive).toHaveBeenCalledTimes(1);
  });

  it("shows a refused zip with the server's reason", async () => {
    api.uploadArchive.mockRejectedValueOnce(new Error("The zip holds a path that escapes its folder."));
    await useUploadTrayStore.getState().enqueue("ws-1", [new File(["PK"], "bad.zip")]);
    await settle();
    expect(useUploadTrayStore.getState().files[0]).toMatchObject({ status: "failed", error: "The zip holds a path that escapes its folder." });
  });
});
