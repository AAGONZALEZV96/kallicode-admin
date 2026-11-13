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
  titulo = "Solicitar Revelación de Datos de Cliente (E6)",
  onConcesionConcedida,
}) => {
  const queryClient = useQueryClient();

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
        setError("Debe especificar el identificador de la organización (tenant_id).");
        return;
      }

      const motivoLimpio = motivo.trim();
      const refEfectiva = referencia.trim() || (PATRON_TICKET.exec(motivoLimpio)?.[0] || "");

      if (motivoLimpio.length < 20) {
        setError("El motivo debe contener al menos 20 caracteres justificando el acceso.");
        return;
      }

      if (!PATRON_TICKET.test(refEfectiva) && !PATRON_TICKET.test(motivoLimpio)) {
        setError("Debe incluir una referencia obligatoria a un ticket válido (ej. KC-1234 o SUP-5678).");
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
          setError(err.message || "Error al procesar la solicitud de concesión.");
        } else {
          setError("Error inesperado al conectar con el servidor.");
        }
      } finally {
        setEnviando(false);
      }
    },
    [tenantId, tenantIdProp, motivo, referencia, alcance, duracionMin, queryClient, onConcesionConcedida]
  );

  return (
    <Modal
      abierto={abierto}
      alCerrar={handleCerrar}
      titulo={titulo}
      idTitulo="titulo-solicitud-concesion"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p style={{ color: "var(--muted)", margin: 0, fontSize: "0.875rem" }}>
          Los datos comerciales y personales están enmascarados por defecto. Una solicitud de concesión aprobada permite revelar temporalmente los
          campos protegidos. Toda consulta con concesión queda registrada de forma inmutable en la cadena de auditoría de la plataforma.
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
            ✓ Concesión autorizada y registrada. Actualizando datos en claro...
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
              Organización (tenant_id) *
            </label>
            <Input
              id="concesion-tenant-id"
              data-testid="input-concesion-tenant"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="org_acme_corp"
              required
              disabled={Boolean(tenantIdProp)}
            />
            {razonSocial && (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)", display: "block", marginTop: "2px" }}>
                Razón Social protegida: <strong>{razonSocial}</strong>
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
              Motivo Justificado (Mínimo 20 caracteres y referencia a ticket) *
            </label>
            <textarea
              id="concesion-motivo"
              data-testid="input-concesion-motivo"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              placeholder="Ej: Revisión de consumo de tokens y auditoría de costes según ticket KC-1049..."
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
              Caracteres: {motivo.trim().length}/20 mín. Debe referenciar KC-#### o SUP-####.
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
              Referencia a Ticket (Opcional si se incluye en el motivo)
            </label>
            <Input
              id="concesion-referencia"
              data-testid="input-concesion-referencia"
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
              placeholder="Ej: KC-1049 o SUP-8821"
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
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
                Alcance Requerido *
              </label>
              <Select
                id="concesion-alcance"
                data-testid="select-concesion-alcance"
                value={alcance}
                onChange={(e) => setAlcance(e.target.value)}
                opciones={[
                  { valor: "datos_negocio", etiqueta: "Datos de Negocio (Recomendado)" },
                  { valor: "expediente", etiqueta: "Expediente Completo" },
                  { valor: "contenido_codigo", etiqueta: "Contenido de Código" },
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
                Duración de la Concesión *
              </label>
              <Select
                id="concesion-duracion"
                data-testid="select-concesion-duracion"
                value={duracionMin}
                onChange={(e) => setDuracionMin(e.target.value)}
                opciones={[
                  { valor: "15", etiqueta: "15 minutos" },
                  { valor: "30", etiqueta: "30 minutos" },
                  { valor: "60", etiqueta: "60 minutos (1 hora)" },
                  { valor: "240", etiqueta: "240 minutos (4 horas)" },
                  { valor: "480", etiqueta: "480 minutos (8 horas)" },
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
              Cancelar
            </Boton>
            <Boton
              type="submit"
              variante="primary"
              data-testid="btn-confirmar-concesion"
              disabled={enviando}
            >
              {enviando ? "Registrando Concesión..." : "Confirmar y Revelar"}
            </Boton>
          </div>
        </form>
      </div>
    </Modal>
  );
};
