/**
 * browser.ts — Worker Mock Service Worker para el entorno del navegador
 */

import { setupWorker } from "msw/browser";
import { handlers } from "./msw_handlers";

export const worker = setupWorker(...handlers);
