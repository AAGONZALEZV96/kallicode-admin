/**
 * clienteApi.test.ts — Pruebas unitarias para el cliente HTTP centralizado
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  clienteApi,
  setTokenGetter,
  setUnauthorizedHandler,
  ApiError,
} from "../clienteApi";

describe("clienteApi", () => {
  const fetchOriginal = globalThis.fetch;

  beforeEach(() => {
    setTokenGetter(() => null);
    setUnauthorizedHandler(() => {});
  });

  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    vi.restoreAllMocks();
  });

  it("1. inyecta automáticamente el encabezado Authorization Bearer cuando existe un token", async () => {
    setTokenGetter(() => "jwt-staff-prueba-123");

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ datos: "ok" }),
    });
    globalThis.fetch = mockFetch;

    const respuesta = await clienteApi.get("/admin/v1/test");

    expect(respuesta).toEqual({ datos: "ok" });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    const [url, opciones] = mockFetch.mock.calls[0];
    expect(url).toBe("/admin/v1/test");
    expect(opciones.headers["Authorization"]).toBe("Bearer jwt-staff-prueba-123");
    expect(opciones.headers["Accept"]).toBe("application/json");
  });

  it("2. omite el encabezado Authorization cuando skipAuth es true", async () => {
    setTokenGetter(() => "jwt-staff-prueba-123");

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ publico: true }),
    });
    globalThis.fetch = mockFetch;

    await clienteApi.post("/admin/v1/auth/login", { email: "a@k.com" }, { skipAuth: true });

    const [, opciones] = mockFetch.mock.calls[0];
    expect(opciones.headers["Authorization"]).toBeUndefined();
  });

  it("3. serializa parámetros de consulta (query params) correctamente", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    globalThis.fetch = mockFetch;

    await clienteApi.get("/admin/v1/business/customers", {
      params: { plan: "growth", estado: "activa", pagina: 1, nulo: null },
    });

    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/admin/v1/business/customers?plan=growth&estado=activa&pagina=1");
  });

  it("4. intercepta respuestas HTTP 401 e invoca el manejador global de no autorizado", async () => {
    const mockHandler = vi.fn();
    setUnauthorizedHandler(mockHandler);

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({
        error: {
          codigo: "TOKEN_INVALIDO",
          mensaje: "Token de acceso expirado",
        },
      }),
    });

    await expect(clienteApi.get("/admin/v1/staff/me")).rejects.toThrow(ApiError);
    expect(mockHandler).toHaveBeenCalledTimes(1);
  });

  it("5. maneja respuestas HTTP 403 y extrae el código ROL_STAFF_INSUFICIENTE", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({
        error: {
          codigo: "ROL_STAFF_INSUFICIENTE",
          mensaje: "El rol no tiene permisos para este recurso",
        },
      }),
    });

    try {
      await clienteApi.get("/admin/v1/business/customers");
      expect.fail("Debería haber lanzado ApiError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(403);
      expect(apiErr.codigo).toBe("ROL_STAFF_INSUFICIENTE");
    }
  });

  it("6. captura errores de red y los normaliza con código ERROR_RED", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    try {
      await clienteApi.get("/admin/v1/ops/agents");
      expect.fail("Debería haber lanzado ApiError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(0);
      expect(apiErr.codigo).toBe("ERROR_RED");
    }
  });

  it("7. maneja respuestas con código 204 No Content devolviendo null", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => ({}),
    });

    const respuesta = await clienteApi.delete("/admin/v1/access-grants/gr_123");
    expect(respuesta).toBeNull();
  });
});
