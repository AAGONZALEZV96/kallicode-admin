/**
 * server.ts — Servidor Mock Service Worker para entorno Node.js y Vitest
 */

import { setupServer } from "msw/node";
import { handlers } from "./msw_handlers";

export const server = setupServer(...handlers);
