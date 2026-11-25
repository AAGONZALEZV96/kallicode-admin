/**
 * AdminLayout.tsx — Layout envolvente de la Consola de Administración
 * 
 * Incluye barra de navegación superior, información del empleado y rol,
 * enlaces dinámicos según permisos RBAC y botón de cierre de sesión.
 */

import React, { useState, useEffect, useRef, createContext, useContext } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth, RolStaff } from "../estado/auth";
import { changeAppLanguage, normalizeLanguage, SupportedLanguage } from "../i18n";
import { Badge } from "./Badge";
import { Boton } from "./Boton";
import { LogoKalliCode } from "./LogoKalliCode";

const AdminLayoutContext = createContext<boolean>(false);

export function useInsideAdminLayout(): boolean {
  return useContext(AdminLayoutContext);
}

export const AdminLayout: React.FC = () => {
  const { t, i18n } = useTranslation();
  const { usuario, logout, cargando } = useAuth();
  const location = useLocation();
  const [menuMovilAbierto, setMenuMovilAbierto] = useState<boolean>(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const wasDrawerOpenRef = useRef<boolean>(false);
  const idiomaActual = normalizeLanguage(i18n.resolvedLanguage || i18n.language);

  const manejarCambioIdioma = (e: React.ChangeEvent<HTMLSelectElement>) => {
    void changeAppLanguage(e.target.value as SupportedLanguage);
  };

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

  // Cerrar drawer móvil automáticamente al navegar entre rutas
  useEffect(() => {
    setMenuMovilAbierto(false);
  }, [location.pathname]);

  // Cerrar drawer móvil con Escape o al ampliar el viewport por encima de 1024px
  useEffect(() => {
    if (typeof window === "undefined") return;

    const manejarResize = () => {
      const esEscritorioPorMatchMedia =
        typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1025px)").matches;
      if (esEscritorioPorMatchMedia || window.innerWidth >= 1025) {
        setMenuMovilAbierto(false);
      }
    };

    const manejarKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuMovilAbierto(false);
      }
    };

    const mq =
      typeof window.matchMedia === "function" ? window.matchMedia("(min-width: 1025px)") : null;

    mq?.addEventListener?.("change", manejarResize);
    window.addEventListener("resize", manejarResize);
    window.addEventListener("keydown", manejarKeyDown);

    return () => {
      mq?.removeEventListener?.("change", manejarResize);
      window.removeEventListener("resize", manejarResize);
      window.removeEventListener("keydown", manejarKeyDown);
    };
  }, []);

  // Evitar scroll en fondo y gestionar foco + focus trap dentro del drawer móvil
  useEffect(() => {
    if (menuMovilAbierto) {
      wasDrawerOpenRef.current = true;
      const prevOverflow = typeof document !== "undefined" ? document.body.style.overflow : "";
      if (typeof document !== "undefined") {
        document.body.style.overflow = "hidden";
      }

      const focusables = drawerRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusables && focusables.length > 0) {
        focusables[0].focus();
      }

      const manejarTabDrawer = (e: KeyboardEvent) => {
        if (e.key !== "Tab" || !drawerRef.current) return;
        const items = Array.from(
          drawerRef.current.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      };

      window.addEventListener("keydown", manejarTabDrawer);
      return () => {
        window.removeEventListener("keydown", manejarTabDrawer);
        if (typeof document !== "undefined") {
          document.body.style.overflow = prevOverflow;
        }
      };
    }

    if (wasDrawerOpenRef.current) {
      wasDrawerOpenRef.current = false;
      mobileToggleRef.current?.focus();
    }
    return undefined;
  }, [menuMovilAbierto]);

  return (
    <div
      className="admin-shell"
      style={{ minHeight: "100vh", display: "flex", flexDirection: "column", backgroundColor: "var(--bg, #0f172a)" }}
    >
      <a href="#main-content" className="skip-link">
        {t("layout.skipToContent")}
      </a>
      {/* Header / Navbar Responsivo */}
      <header className="admin-header">
        <div className="admin-brand-wrap">
          <Link
            to="/"
            onClick={cerrarMenuMovil}
            className="admin-brand-link"
          >
            <LogoKalliCode variante="isotipo" altura={24} />
            <span>{t("layout.consoleTitle")}</span>
          </Link>

          {/* Menú de Escritorio (>= 1025px) */}
          <nav className="nav-desktop" aria-label={t("layout.nav.desktopAria")}>
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
                  {t("layout.nav.overview")}
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
                  {t("layout.nav.subscriptions")}
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
                  {t("layout.nav.tokens")}
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
                {t("layout.nav.customers")}
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
                  {t("layout.nav.agents")}
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
                  {t("layout.nav.models")}
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
                {t("layout.nav.sla")}
              </Link>
              </>
            )}
          </nav>
        </div>

        {/* Sección Usuario de Escritorio (>= 900px) */}
        <div className="nav-user-desktop">
          <select
            data-testid="selector-idioma"
            aria-label={t("layout.language.ariaLabel")}
            value={idiomaActual}
            onChange={manejarCambioIdioma}
            className="kc-select"
            style={{
              fontSize: "0.75rem",
              padding: "0.25rem 0.5rem",
              minWidth: "96px",
              width: "auto",
              backgroundColor: "var(--surface2, #334155)",
              color: "var(--text, #f8fafc)",
              border: "1px solid var(--border, #475569)",
              borderRadius: "var(--radius-sm, 0.375rem)",
            }}
          >
            <option value="es">{t("layout.language.es")}</option>
            <option value="en">{t("layout.language.en")}</option>
          </select>

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
            {t("layout.logout")}
          </Boton>
        </div>

        {/* Controles para Móvil (< 900px) */}
        <div className="mobile-controls" style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {usuario && (
            <Badge variante={getBadgeVariant(rol)}>{rol}</Badge>
          )}
          <button
            ref={mobileToggleRef}
            type="button"
            className="nav-mobile-toggle"
            onClick={() => setMenuMovilAbierto((prev) => !prev)}
            aria-label={menuMovilAbierto ? t("layout.mobile.closeMenu") : t("layout.mobile.openMenu")}
            aria-expanded={menuMovilAbierto}
          >
            {menuMovilAbierto ? "✕" : "☰"}
          </button>
        </div>
      </header>

      {/* Cajón Desplegable Móvil (<= 1024px) */}
      {menuMovilAbierto && (
        <div
          ref={drawerRef}
          className="nav-mobile-drawer"
          role="dialog"
          aria-modal="true"
          aria-label={t("layout.mobile.drawerLabel")}
        >
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

          <nav aria-label={t("layout.nav.mobileAria")} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {tienePermisoNegocio && (
              <>
                <Link
                  to="/overview"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/overview") ? "active" : ""}`}
                >
                  {t("layout.nav.overview")}
                </Link>
                <Link
                  to="/business/subscriptions"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${
                    isActive("/business/subscriptions") || isActive("/subscriptions") ? "active" : ""
                  }`}
                >
                  {t("layout.nav.subscriptions")}
                </Link>
                <Link
                  to="/business/tokens"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/business/tokens") || isActive("/tokens") ? "active" : ""}`}
                >
                  {t("layout.nav.tokens")}
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
                {t("layout.nav.customers")}
              </Link>
            )}

            {tienePermisoOps && (
              <Link
                to="/ops/agents"
                onClick={cerrarMenuMovil}
                className={`nav-link-mobile ${isActive("/ops/agents") ? "active" : ""}`}
              >
                {t("layout.nav.agents")}
              </Link>
            )}

            {tienePermisoSla && (
              <>
                <Link
                  to="/ops/models"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/ops/models") ? "active" : ""}`}
                >
                  {t("layout.nav.models")}
                </Link>
                <Link
                  to="/ops/sla"
                  onClick={cerrarMenuMovil}
                  className={`nav-link-mobile ${isActive("/ops/sla") ? "active" : ""}`}
                >
                  {t("layout.nav.sla")}
                </Link>
              </>
            )}
          </nav>

          <div style={{ marginTop: "auto", paddingTop: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.8125rem", color: "var(--muted)" }}>
              <span>{t("layout.language.label")}</span>
              <select
                data-testid="selector-idioma-movil"
                aria-label={t("layout.language.ariaLabel")}
                value={idiomaActual}
                onChange={manejarCambioIdioma}
                className="kc-select"
              >
                <option value="es">{t("layout.language.es")}</option>
                <option value="en">{t("layout.language.en")}</option>
              </select>
            </label>

            <Boton
              variante="secondary"
              tamano="md"
              onClick={() => {
                cerrarMenuMovil();
                void logout();
              }}
              style={{ width: "100%", justifyContent: "center" }}
            >
              {t("layout.logout")}
            </Boton>
          </div>
        </div>
      )}

      {/* Contenido Principal */}
      <main id="main-content" tabIndex={-1} className="admin-main">
        <AdminLayoutContext.Provider value={true}>
          <Outlet />
        </AdminLayoutContext.Provider>
      </main>
    </div>
  );
};
