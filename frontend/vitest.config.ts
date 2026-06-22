import path from "node:path"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vitest/config"

// Separate from vite.config.ts so the TanStack router plugin (which scans routes)
// is not loaded during unit tests.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests-unit/setup.ts"],
    include: ["tests-unit/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/smartforge/**"],
      reporter: ["text", "html"],
    },
  },
})
