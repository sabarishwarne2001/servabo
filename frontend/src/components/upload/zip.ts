/**
 * Final session 1 (2A): a zip of documents is accepted on every plan and workspace. The server unpacks it and adds each
 * document through the ordinary intake path, so the workspace's file types and the plan's limits apply to every file in
 * it; the zip itself is only bounded by ZIP_UPLOAD_MAX_MB on the server. Shared by the Documents page's tray and, since
 * Final session 2A, the global upload tray.
 */
export const ZIP_MAX_MB = 256;

export const isZip = (file: { readonly name: string }): boolean => file.name.toLowerCase().endsWith(".zip");
