/**
 * queryClient.ts — Configuración global de TanStack Query para la Consola Admin
 */

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30 segundos de frescura por defecto
      gcTime: 5 * 60 * 1000, // 5 minutos de tiempo en caché (reemplaza cacheTime en TanStack Query v5)
      retry: (conteoFallos, error: unknown) => {
        // No reintentar ante errores de autenticación o autorización
        if (
          error &&
          typeof error === "object" &&
          "status" in error &&
          (error.status === 401 || error.status === 403 || error.status === 404)
        ) {
          return false;
        }
        return conteoFallos < 2;
      },
      refetchOnWindowFocus: false, // El polling en vivo se gestiona con useLiveRefresh
    },
    mutations: {
      retry: false,
    },
  },
});

/**
 * Limpia la totalidad de cachés de consultas. Invocado al cerrar sesión.
 */
export function limpiarQueryCache(): void {
  queryClient.clear();
}
