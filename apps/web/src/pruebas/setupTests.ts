/**
 * setupTests.ts — Configuración global del ciclo de vida de MSW para Vitest
 */

import { beforeAll, afterEach, afterAll } from "vitest";
import i18n from "../i18n";
import { server } from "./server";
import { resetMockState } from "./msw_handlers";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "bypass" });
});

afterEach(async () => {
  server.resetHandlers();
  resetMockState();
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear();
  }
  await i18n.changeLanguage("es");
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.lang = "es";
  }
});

afterAll(() => {
  server.close();
});
