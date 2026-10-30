/**
 * clienteApi.ts — Cliente HTTP centralizado para la Consola Admin (§18)
 * 
 * Inyecta automáticamente Authorization: Bearer <token>, gestiona cabeceras
 * estándar de JSON y normaliza errores homogéneamente para la SPA.
 */

export interface ErrorDetalle {
  codigo?: string;
  code?: string;
  mensaje?: string;
  message?: string;
  detalle?: unknown;
  timestamp?: string;
}

export interface ErrorStandardResponse {
  error: ErrorDetalle;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly codigo: string;
  public readonly detalle?: unknown;

  constructor(status: number, codigo: string, mensaje: string, detalle?: unknown) {
    super(mensaje);
    this.name = "ApiError";
    this.status = status;
    this.codigo = codigo;
    this.detalle = detalle;
  }
}

type TokenGetter = () => string | null;
type UnauthorizedHandler = () => void;

let obtenerToken: TokenGetter = () => null;
let manejarNoAutorizado: UnauthorizedHandler = () => {};

/** Configura la función que suministra el token JWT en memoria. */
export function setTokenGetter(getter: TokenGetter): void {
  obtenerToken = getter;
}

/** Configura la acción global ante respuestas HTTP 401 (ej. expiración de sesión). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  manejarNoAutorizado = handler;
}

export interface PeticionOpciones extends RequestInit {
  params?: Record<string, string | number | boolean | null | undefined>;
  skipAuth?: boolean;
}

/**
 * Realiza una petición HTTP con inyección automática de cabeceras y manejo de errores.
 */
export async function peticionApi<T = unknown>(
  ruta: string,
  opciones: PeticionOpciones = {}
): Promise<T> {
  const { params, skipAuth = false, headers: cabecerasCustom, body, ...restoOpciones } = opciones;

  let url = ruta;
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [clave, valor] of Object.entries(params)) {
      if (valor !== null && valor !== undefined) {
        searchParams.append(clave, String(valor));
      }
    }
    const query = searchParams.toString();
    if (query) {
      url += (url.includes("?") ? "&" : "?") + query;
    }
  }

  const cabeceras: Record<string, string> = {
    Accept: "application/json",
    ...((cabecerasCustom as Record<string, string>) || {}),
  };

  if (!(body instanceof FormData) && !cabeceras["Content-Type"]) {
    cabeceras["Content-Type"] = "application/json";
  }

  if (!skipAuth) {
    const token = obtenerToken();
    if (token && !cabeceras["Authorization"]) {
      cabeceras["Authorization"] = `Bearer ${token}`;
    }
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(url, {
      ...restoOpciones,
      headers: cabeceras,
      body,
    });
  } catch (errorRed) {
    throw new ApiError(
      0,
      "ERROR_RED",
      "No fue posible conectar con el servidor. Verifica tu conexión de red.",
      errorRed
    );
  }

  if (!respuesta.ok) {
    let errorData: ErrorDetalle = {};
    try {
      const cuerpo = await respuesta.json();
      if (cuerpo && typeof cuerpo === "object") {
        if ("error" in cuerpo && typeof cuerpo.error === "object") {
          errorData = cuerpo.error as ErrorDetalle;
        } else {
          errorData = cuerpo as ErrorDetalle;
        }
      }
    } catch {
      // Si la respuesta no es JSON válido
      errorData = {
        mensaje: respuesta.statusText || `Error HTTP ${respuesta.status}`,
      };
    }

    const codigo =
      errorData.codigo ||
      errorData.code ||
      (respuesta.status === 401
        ? "TOKEN_INVALIDO"
        : respuesta.status === 403
        ? "ROL_STAFF_INSUFICIENTE"
        : respuesta.status === 404
        ? "NO_ENCONTRADO"
        : "ERROR_SERVIDOR");

    const mensaje =
      errorData.mensaje ||
      errorData.message ||
      (respuesta.status === 401
        ? "Sesión no válida o expirada."
        : respuesta.status === 403
        ? "No tienes permisos suficientes para realizar esta acción."
        : `Error ${respuesta.status}`);

    if (respuesta.status === 401 && !skipAuth) {
      manejarNoAutorizado();
    }

    throw new ApiError(respuesta.status, codigo, mensaje, errorData.detalle);
  }

  if (respuesta.status === 204) {
    return null as T;
  }

  return (await respuesta.json()) as T;
}

export const clienteApi = {
  get: <T = unknown>(ruta: string, opciones?: PeticionOpciones) =>
    peticionApi<T>(ruta, { ...opciones, method: "GET" }),

  post: <T = unknown>(ruta: string, datos?: unknown, opciones?: PeticionOpciones) =>
    peticionApi<T>(ruta, {
      ...opciones,
      method: "POST",
      body: datos instanceof FormData ? datos : JSON.stringify(datos),
    }),

  put: <T = unknown>(ruta: string, datos?: unknown, opciones?: PeticionOpciones) =>
    peticionApi<T>(ruta, {
      ...opciones,
      method: "PUT",
      body: datos instanceof FormData ? datos : JSON.stringify(datos),
    }),

  patch: <T = unknown>(ruta: string, datos?: unknown, opciones?: PeticionOpciones) =>
    peticionApi<T>(ruta, {
      ...opciones,
      method: "PATCH",
      body: datos instanceof FormData ? datos : JSON.stringify(datos),
    }),

  delete: <T = unknown>(ruta: string, opciones?: PeticionOpciones) =>
    peticionApi<T>(ruta, { ...opciones, method: "DELETE" }),
};
