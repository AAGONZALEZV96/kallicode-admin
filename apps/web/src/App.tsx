/**
 * App.tsx — Componente raíz de la SPA kallicode-admin
 * 
 * Configura la jerarquía global de proveedores:
 * ErrorBoundary -> QueryClientProvider -> AuthProvider -> AppRouter
 */

import React from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";
import { queryClient } from "./api/queryClient";
import { AuthProvider } from "./estado/auth";
import { ErrorBoundary } from "./componentes/ErrorBoundary";
import { AppRouter } from "./router/AppRouter";

export const App: React.FC = () => {
  return (
    <I18nextProvider i18n={i18n}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <AppRouter />
          </AuthProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </I18nextProvider>
  );
};

export default App;
