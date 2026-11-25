/**
 * SolicitudConcesionModal.tsx — Modal de Solicitud de Concesión y Revelación E6
 *
 * Permite al personal autorizado solicitar una concesión de acceso temporal
 * (POST /admin/v1/access-grants) para revelar datos de clientes enmascarados,
 * asegurando la justificación obligatoria (mínimo 20 caracteres y ticket KC/SUP)
 * y la auditoría append-only inmutable en admin.staff_actions.
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { peticionApi, ApiError } from "../api/clienteApi";
import { Modal } from "./Modal";
import { Boton } from "./Boton";
import { Input } from "./Input";
import { Select } from "./Select";

const PATRON_TICKET = /(KC|SUP)-\d{3,}/i;

export interface SolicitudConcesionModalProps {
  abierto: boolean;
  alCerrar: () => void;
  tenantId?: string;
  razonSocial?: string;
  titulo?: string;
  onConcesionConcedida?: () => void;
}

export const SolicitudConcesionModal: React.FC<SolicitudConcesionModalProps> = ({
  abierto,
  alCerrar,
  tenantId: tenantIdProp = "",
  razonSocial = "",
  titulo,
  onConcesionConcedida,
}) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const tituloEfectivo = titulo ?? t("components.accessGrant.defaultTitle");

  const [tenantId, setTenantId] = useState<string>(tenantIdProp);
  const [motivo, setMotivo] = useState<string>("");
  const [referencia, setReferencia] = useState<string>("");
  const [alcance, setAlcance] = useState<string>("datos_negocio");
  const [duracionMin, setDuracionMin] = useState<string>("240");
  const [enviando, setEnviando] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<boolean>(false);

  const prevAbiertoRef = useRef(false);

  // Inicializar/limpiar formulario únicamente cuando el modal pasa de cerrado a abierto
  useEffect(() => {
    if (abierto && !prevAbiertoRef.current) {
      setTenantId(tenantIdProp);
      setMotivo("");
      setReferencia("");
      setAlcance("datos_negocio");
      setDuracionMin("240");
      setError(null);
      setExito(false);
    }
    prevAbiertoRef.current = abierto;
  }, [abierto, tenantIdProp]);

  const handleCerrar = useCallback(() => {
    setError(null);
    setExito(false);
    alCerrar();
  }, [alCerrar]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);

      const targetTenant = tenantId.trim() || tenantIdProp.trim();
      if (!targetTenant) {
        setError(t("components.accessGrant.validation.missingTenant"));
        return;
      }

      const motivoLimpio = motivo.trim();
      const refEfectiva = referencia.trim() || (PATRON_TICKET.exec(motivoLimpio)?.[0] || "");

      if (motivoLimpio.length < 20) {
        setError(t("components.accessGrant.validation.minReason"));
        return;
      }

      if (!PATRON_TICKET.test(refEfectiva) && !PATRON_TICKET.test(motivoLimpio)) {
        setError(t("components.accessGrant.validation.missingTicket"));
        return;
      }

      setEnviando(true);
      try {
        await peticionApi("/admin/v1/access-grants", {
          method: "POST",
          body: JSON.stringify({
            tenant_id: targetTenant,
            alcance,
            motivo: motivoLimpio,
            duracion_min: Number(duracionMin),
            referencia: refEfectiva || undefined,
          }),
        });

        setExito(true);
        // Invalidar cachés relacionadas con negocio, clientes y consumo de tokens
        await queryClient.invalidateQueries({ queryKey: ["business-usage-tokens"] });
        await queryClient.invalidateQueries({ queryKey: ["business-subscriptions"] });
        await queryClient.invalidateQueries({ queryKey: ["business-upgrade-requests"] });
        await queryClient.invalidateQueries({ queryKey: ["business-customers"] });
        await queryClient.invalidateQueries({ queryKey: ["business-customer-detail"] });

        if (onConcesionConcedida) {
          onConcesionConcedida();
        }

        setTimeout(() => {
          handleCerrar();
        }, 800);
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          setError(err.message || t("components.accessGrant.validation.apiError"));
        } else {
          setError(t("components.accessGrant.validation.unexpectedError"));
        }
      } finally {
        setEnviando(false);
      }
    },
    [tenantId, tenantIdProp, motivo, referencia, alcance, duracionMin, queryClient, onConcesionConcedida, handleCerrar, t]
  );

  return (
    <Modal
      abierto={abierto}
      alCerrar={handleCerrar}
      titulo={tituloEfectivo}
      idTitulo="titulo-solicitud-concesion"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.875rem" }}>
          {t("components.accessGrant.notice")}
        </p>

        {exito && (
          <div
            data-testid="exito-concesion"
            role="status"
            aria-live="polite"
            style={{
              padding: "0.75rem",
              borderRadius: "var(--radius-sm)",
              backgroundColor: "var(--surface2)",
              color: "var(--good)",
              border: "1px solid var(--good)",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            {t("components.accessGrant.success")}
          </div>
        )}

        {error && (
          <div
            data-testid="error-validacion-modal"
            role="alert"
            style={{
              padding: "0.75rem",
              borderRadius: "var(--radius-sm)",
              backgroundColor: "var(--surface2)",
              color: "var(--bad)",
              border: "1px solid var(--bad)",
              fontSize: "0.875rem",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div>
            <label
              htmlFor="concesion-tenant-id"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                marginBottom: "4px",
                color: "var(--text)",
              }}
            >
              {t("components.accessGrant.fields.tenantId")}
            </label>
            <Input
              id="concesion-tenant-id"
              data-testid="input-concesion-tenant"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder={t("components.accessGrant.fields.tenantPlaceholder")}
              required
              disabled={Boolean(tenantIdProp)}
            />
            {razonSocial && (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)", display: "block", marginTop: "2px" }}>
                {t("components.accessGrant.fields.protectedName")} <strong>{razonSocial}</strong>
              </span>
            )}
          </div>

          <div>
            <label
              htmlFor="concesion-motivo"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                marginBottom: "4px",
                color: "var(--text)",
              }}
            >
              {t("components.accessGrant.fields.reason")}
            </label>
            <textarea
              id="concesion-motivo"
              data-testid="input-concesion-motivo"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              placeholder={t("components.accessGrant.fields.reasonPlaceholder")}
              rows={3}
              style={{
                width: "100%",
                padding: "0.5rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                backgroundColor: "var(--surface)",
                color: "var(--text)",
                fontFamily: "inherit",
                fontSize: "0.875rem",
                resize: "vertical",
                boxSizing: "border-box",
              }}
              required
            />
            <span
              style={{
                fontSize: "0.75rem",
                color: motivo.trim().length >= 20 ? "var(--good)" : "var(--muted)",
                display: "block",
                marginTop: "2px",
              }}
            >
              {t("components.accessGrant.fields.charCount", { count: motivo.trim().length })}
            </span>
          </div>

          <div>
            <label
              htmlFor="concesion-referencia"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                marginBottom: "4px",
                color: "var(--text)",
              }}
            >
              {t("components.accessGrant.fields.reference")}
            </label>
            <Input
              id="concesion-referencia"
              data-testid="input-concesion-referencia"
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
              placeholder={t("components.accessGrant.fields.referencePlaceholder")}
            />
          </div>

          <div className="kc-modal-grid-2">
            <div>
              <label
                htmlFor="concesion-alcance"
                style={{
                  display: "block",
                  fontSize: "0.8125rem",
                  fontWeight: 500,
                  marginBottom: "4px",
                  color: "var(--text)",
                }}
              >
                {t("components.accessGrant.fields.scope")}
              </label>
              <Select
                id="concesion-alcance"
                data-testid="select-concesion-alcance"
                value={alcance}
                onChange={(e) => setAlcance(e.target.value)}
                opciones={[
                  { valor: "datos_negocio", etiqueta: t("components.accessGrant.scopes.datos_negocio") },
                  { valor: "expediente", etiqueta: t("components.accessGrant.scopes.expediente") },
                  { valor: "contenido_codigo", etiqueta: t("components.accessGrant.scopes.contenido_codigo") },
                ]}
              />
            </div>

            <div>
              <label
                htmlFor="concesion-duracion"
                style={{
                  display: "block",
                  fontSize: "0.8125rem",
                  fontWeight: 500,
                  marginBottom: "4px",
                  color: "var(--text)",
                }}
              >
                {t("components.accessGrant.fields.duration")}
              </label>
              <Select
                id="concesion-duracion"
                data-testid="select-concesion-duracion"
                value={duracionMin}
                onChange={(e) => setDuracionMin(e.target.value)}
                opciones={[
                  { valor: "15", etiqueta: t("components.accessGrant.durations.15") },
                  { valor: "30", etiqueta: t("components.accessGrant.durations.30") },
                  { valor: "60", etiqueta: t("components.accessGrant.durations.60") },
                  { valor: "240", etiqueta: t("components.accessGrant.durations.240") },
                  { valor: "480", etiqueta: t("components.accessGrant.durations.480") },
                ]}
              />
            </div>
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: "0.75rem",
              marginTop: "0.5rem",
              flexWrap: "wrap",
            }}
          >
            <Boton
              type="button"
              variante="secondary"
              onClick={handleCerrar}
              disabled={enviando}
            >
              {t("common.actions.cancel")}
            </Boton>
            <Boton
              type="submit"
              variante="primary"
              data-testid="btn-confirmar-concesion"
              disabled={enviando}
            >
              {enviando ? t("components.accessGrant.submitting") : t("components.accessGrant.submit")}
            </Boton>
          </div>
        </form>
      </div>
    </Modal>
  );
};
