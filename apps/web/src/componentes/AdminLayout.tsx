/**
 * AdminLayout.tsx — Layout envolvente de la Consola de Administración
 * 
 * Incluye barra de navegación superior, información del empleado y rol,
 * enlaces dinámicos según permisos RBAC y botón de cierre de sesión.
 */

import React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth, RolStaff } from "../estado/auth";
import { Badge } from "./Badge";
import { Boton } from "./Boton";

export const AdminLayout: React.FC = () => {
  const { usuario, logout, cargando } = useAuth();
  const location = useLocation();

  const rol = usuario?.role as RolStaff | undefined;
  const tienePermisoNegocio = rol === "staff_negocio" || rol === "staff_admin";
  const tienePermisoClientes = rol === "staff_soporte" || rol === "staff_negocio" || rol === "staff_admin";
  const tienePermisoOps = rol === "staff_operaciones" || rol === "staff_admin";

  const getBadgeVariant = (r?: RolStaff): "accent" | "warn" | "good" | "neutro" => {
    switch (r) {
      case "staff_admin":
        return "accent";
      case "staff_negocio":
        return "accent";
      case "staff_operaciones":
        return "warn";
      case "staff_soporte":
        return "good";
      default:
        return "neutro";
    }
  };

  const isActive = (path: string) => location.pathname === path;

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", backgroundColor: "var(--bg, #0f172a)" }}>
      {/* Header / Navbar */}
      <header
        style={{
          height: "64px",
          backgroundColor: "var(--card, #1e293b)",
          borderBottom: "1px solid var(--border, #334155)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 1.5rem",
          position: "sticky",
          top: 0,
          zIndex: 40,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "2rem" }}>
          <Link
            to="/"
            style={{
              fontSize: "1.125rem",
              fontWeight: 700,
              color: "var(--text, #f8fafc)",
              textDecoration: "none",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <span style={{ color: "var(--accent, #38bdf8)" }}>⚙</span>
            KalliCode Consola
          </Link>

          <nav style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {tienePermisoNegocio && (
              <Link
                to="/overview"
                style={{
                  fontSize: "0.875rem",
                  padding: "0.375rem 0.75rem",
                  borderRadius: "0.375rem",
                  textDecoration: "none",
                  color: isActive("/overview") ? "var(--text, #f8fafc)" : "var(--muted, #94a3b8)",
                  backgroundColor: isActive("/overview") ? "var(--surface2, #334155)" : "transparent",
                  fontWeight: isActive("/overview") ? 600 : 400,
                }}
              >
                Panel Negocio
              </Link>
            )}

            {tienePermisoClientes && (
              <Link
                to="/business/customers"
                style={{
                  fontSize: "0.875rem",
                  padding: "0.375rem 0.75rem",
                  borderRadius: "0.375rem",
                  textDecoration: "none",
                  color:
                    isActive("/business/customers") || isActive("/customers")
                      ? "var(--text, #f8fafc)"
                      : "var(--muted, #94a3b8)",
                  backgroundColor:
                    isActive("/business/customers") || isActive("/customers")
                      ? "var(--surface2, #334155)"
                      : "transparent",
                  fontWeight:
                    isActive("/business/customers") || isActive("/customers") ? 600 : 400,
                }}
              >
                Clientes
              </Link>
            )}

            {tienePermisoOps && (
              <>
                <Link
                  to="/ops/agents"
                  style={{
                    fontSize: "0.875rem",
                    padding: "0.375rem 0.75rem",
                    borderRadius: "0.375rem",
                    textDecoration: "none",
                    color: isActive("/ops/agents") ? "var(--text, #f8fafc)" : "var(--muted, #94a3b8)",
                    backgroundColor: isActive("/ops/agents") ? "var(--surface2, #334155)" : "transparent",
                    fontWeight: isActive("/ops/agents") ? 600 : 400,
                  }}
                >
                  Agentes
                </Link>
                <Link
                  to="/ops/models"
                  style={{
                    fontSize: "0.875rem",
                    padding: "0.375rem 0.75rem",
                    borderRadius: "0.375rem",
                    textDecoration: "none",
                    color: isActive("/ops/models") ? "var(--text, #f8fafc)" : "var(--muted, #94a3b8)",
                    backgroundColor: isActive("/ops/models") ? "var(--surface2, #334155)" : "transparent",
                    fontWeight: isActive("/ops/models") ? 600 : 400,
                  }}
                >
                  Modelos
                </Link>
                <Link
                  to="/ops/sla"
                  style={{
                    fontSize: "0.875rem",
                    padding: "0.375rem 0.75rem",
                    borderRadius: "0.375rem",
                    textDecoration: "none",
                    color: isActive("/ops/sla") ? "var(--text, #f8fafc)" : "var(--muted, #94a3b8)",
                    backgroundColor: isActive("/ops/sla") ? "var(--surface2, #334155)" : "transparent",
                    fontWeight: isActive("/ops/sla") ? 600 : 400,
                  }}
                >
                  SLA
                </Link>
              </>
            )}
          </nav>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          {usuario && (
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: "0.8125rem", fontWeight: 500, color: "var(--text, #f8fafc)" }}>
                  {usuario.nombre || usuario.email}
                </div>
                <div style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)" }}>
                  {usuario.email}
                </div>
              </div>
              <Badge variante={getBadgeVariant(rol)}>{rol}</Badge>
            </div>
          )}

          <Boton
            variante="ghost"
            tamano="sm"
            onClick={logout}
            cargando={cargando}
            style={{ color: "var(--muted, #94a3b8)" }}
          >
            Cerrar Sesión
          </Boton>
        </div>
      </header>

      {/* Contenido Principal */}
      <main style={{ flex: 1, padding: "1.5rem", maxWidth: "1400px", margin: "0 auto", width: "100%", boxSizing: "border-box" }}>
        <Outlet />
      </main>
    </div>
  );
};
