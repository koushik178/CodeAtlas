import { defineConfig } from "vitest/config";

export default defineConfig({
  define: {
    "process.env.NEXT_PUBLIC_API_URL": JSON.stringify("http://api.test"),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    fileParallelism: false,
    maxWorkers: 1,
  },
});
