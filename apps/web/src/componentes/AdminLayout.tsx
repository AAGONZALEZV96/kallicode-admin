/**
 * AdminLayout.tsx — Layout envolvente de la Consola de Administración
 * 
 * Incluye barra de navegación superior, información del empleado y rol,
 * enlaces dinámicos según permisos RBAC y botón de cierre de sesión.
 */

import React, { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth, RolStaff } from "../estado/auth";
import { Badge } from "./Badge";
import { Boton } from "./Boton";

export const AdminLayout: React.FC = () => {
  const { usuario, logout, cargando } = useAuth();
  const location = useLocation();
  const [menuMovilAbierto, setMenuMovilAbierto] = useState<boolean>(false);

  const rol = usuario?.role as RolStaff | undefined;
  const tienePermisoNegocio = rol === "staff_negocio" || rol === "staff_admin";
  const tienePermisoClientes = rol === "staff_soporte" || rol === "staff_negocio" || rol === "staff_admin";
  const tienePermisoOps = rol === "staff_operaciones" || rol === "staff_admin";
  const tienePermisoSla =
    rol === "staff_operaciones" || rol === "staff_negocio" || rol === "staff_admin";

  const getBadgeVariant = (r?: RolStaff): "accent" | "warn" | "good" | "neutro" => {
    switch (r) {
      case "staff_admin":
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

  const cerrarMenuMovil = () => setMenuMovilAbierto(false);

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", backgroundColor: "var(--bg, #0f172a)" }}>
      {/* Header / Navbar Responsivo */}
      <header className="admin-header">
        <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
          <Link
            to="/"
            onClick={cerrarMenuMovil}
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

          {/* Menú de Escritorio (>= 900px) */}
          <nav className="nav-desktop">
            {tienePermisoNegocio && (
              <>
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
                <Link
                  to="/business/subscriptions"
                  style={{
                    fontSize: "0.875rem",
                    padding: "0.375rem 0.75rem",
                    borderRadius: "0.375rem",
                    textDecoration: "none",
                    color:
                      isActive("/business/subscriptions") || isActive("/subscriptions")
                        ? "var(--text, #f8fafc)"
                        : "var(--muted, #94a3b8)",
                    backgroundColor:
                      isActive("/business/subscriptions") || isActive("/subscriptions")
                        ? "var(--surface2, #334155)"
                        : "transparent",
                    fontWeight:
                      isActive("/business/subscriptions") || isActive("/subscriptions") ? 600 : 400,
                  }}
                >
                  Suscripciones
                </Link>
                <Link
                  to="/business/tokens"
                  style={{
                    fontSize: "0.875rem",
                    padding: "0.375rem 0.75rem",
                    borderRadius: "0.375rem",
                    textDecoration: "none",
                    color:
                      isActive("/business/tokens") || isActive("/tokens")
                        ? "var(--text, #f8fafc)"
                        : "var(--muted, #94a3b8)",
                    backgroundColor:
                      isActive("/business/tokens") || isActive("/tokens")
                        ? "var(--surface2, #334155)"
                        : "transparent",
                    fontWeight:
                      isActive("/business/tokens") || isActive("/tokens") ? 600 : 400,
                  }}
                >
                  Consumo Tokens
                </Link>
              </>
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
              </>
            )}

            {tienePermisoSla && (
              <>
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

        {/* Sección Usuario de Escritorio (>= 900px) */}
        <div className="nav-user-desktop">
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

        {/* Controles para Móvil (< 900px) */}
        <div className="mobile-controls" style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {usuario && (
            <Badge variante={getBadgeVariant(rol)}>{rol}</Badge>
          )}
          <button
            type="button"
            className="nav-mobile-toggle"
            onClick={() => setMenuMovilAbierto((prev) => !prev)}
            aria-label={menuMovilAbierto ? "Cerrar menú de navegación" : "Abrir menú de navegación"}
            aria-expanded={menuMovilAbierto}
          >
            {menuMovilAbierto ? "✕" : "☰"}
          </button>
        </div>
      </header>

      {/* Cajón Desplegable Móvil (< 900px) */}
      {menuMovilAbierto && (
        <div className="nav-mobile-drawer" role="dialog" aria-modal="true" aria-label="Navegación móvil">
          {usuario && (
            <div
              style={{
                padding: "1rem",
                backgroundColor: "var(--surface)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                gap: "0.375rem",
              }}
            >
              <div style={{ fontWeight: 600, color: "var(--text)" }}>{usuario.nombre || usuario.email}</div>
              <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{usuario.email}</div>
              <div style={{ marginTop: "0.25rem" }}>
                <Badge variante={getBadgeVariant(rol)}>{rol}</Badge>
              </div>
            </div>
          )}

          <nav style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {tienePermisoNegocio && (
              <>
                <Link
                  to="/overview"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/overview") ? "active" : ""}`}
                >
                  Panel Negocio
                </Link>
                <Link
                  to="/business/subscriptions"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${
                    isActive("/business/subscriptions") || isActive("/subscriptions") ? "active" : ""
                  }`}
                >
                  Suscripciones
                </Link>
                <Link
                  to="/business/tokens"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/business/tokens") || isActive("/tokens") ? "active" : ""}`}
                >
                  Consumo Tokens
                </Link>
              </>
            )}

            {tienePermisoClientes && (
              <Link
                to="/business/customers"
                onClick={cerrarMenuMovil}
                className={`nav-link-mobile ${
                  isActive("/business/customers") || isActive("/customers") ? "active" : ""
                }`}
              >
                Clientes
              </Link>
            )}

            {tienePermisoOps && (
              <Link
                to="/ops/agents"
                onClick={cerrarMenuMovil}
                className={`nav-link-mobile ${isActive("/ops/agents") ? "active" : ""}`}
              >
                Agentes
              </Link>
            )}

            {tienePermisoSla && (
              <>
                <Link
                  to="/ops/models"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/ops/models") ? "active" : ""}`}
                >
                  Modelos
                </Link>
                <Link
                  to="/ops/sla"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/ops/sla") ? "active" : ""}`}
                >
                  SLA
                </Link>
              </>
            )}
          </nav>

          <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
            <Boton
              variante="secondary"
              tamano="md"
              onClick={() => {
                cerrarMenuMovil();
                void logout();
              }}
              style={{ width: "100%", justifyContent: "center" }}
            >
              Cerrar Sesión
            </Boton>
          </div>
        </div>
      )}

      {/* Contenido Principal */}
      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  );
};
