/**
 * App.tsx — Componente raíz de la SPA kallicode-admin
 * 
 * Configura la jerarquía global de proveedores:
 * ErrorBoundary -> QueryClientProvider -> AuthProvider -> AppRouter
 */

import React from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import { AuthProvider } from "./estado/auth";
import { ErrorBoundary } from "./componentes/ErrorBoundary";
import { AppRouter } from "./router/AppRouter";

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
};

export default App;
