import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** Session J: the frontend's unit-test runner. `npm run test:unit`; the browser specs live in e2e/. */
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    restoreMocks: true,
  },
});
