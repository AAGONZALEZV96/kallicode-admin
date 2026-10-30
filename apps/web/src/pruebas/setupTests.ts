/**
 * setupTests.ts — Configuración global del ciclo de vida de MSW para Vitest
 */

import { beforeAll, afterEach, afterAll } from "vitest";
import { server } from "./server";
import { resetMockState } from "./msw_handlers";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "bypass" });
});

afterEach(() => {
  server.resetHandlers();
  resetMockState();
});

afterAll(() => {
  server.close();
});
