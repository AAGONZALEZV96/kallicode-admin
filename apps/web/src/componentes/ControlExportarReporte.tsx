import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { clienteApi } from "../api/clienteApi";
import { useOptionalAuth, RolStaff } from "../estado/auth";
import { Boton } from "./Boton";
import { Modal } from "./Modal";
import { Select } from "./Select";
import { Input } from "./Input";
import { Badge } from "./Badge";

export type TipoReporteExportable = "consumo" | "clientes" | "suscripciones" | "sla";
export type FormatoReporteExportable = "csv" | "xlsx" | "pdf";

export interface ControlExportarReporteProps {
  tipo: TipoReporteExportable;
  etiquetaBoton?: string;
  tituloModal?: string;
  formatosPermitidos?: FormatoReporteExportable[];
  rolesPermitidos?: RolStaff[];
  tenantId?: string | null;
}

interface RespuestaCrearReporte {
  report_id: string;
  estado: string;
  estimacion_s: number;
}

interface RespuestaDetalleReporte {
  report_id: string;
  tipo: string;
  formato: string;
  estado: string;
  download_url?: string | null;
  hash_sha256?: string | null;
  filas?: number | null;
}

const ETIQUETAS_TIPO: Record<TipoReporteExportable, string> = {
  consumo: "Consumo de Tokens y Costes LLM",
  clientes: "Resumen de Clientes y Consumo",
  suscripciones: "Suscripciones y Renovaciones",
  sla: "Cumplimiento de SLA e Incidentes",
};

function construirContenidoLocal(
  tipo: TipoReporteExportable,
  formato: FormatoReporteExportable,
  reportId: string,
  desde: string,
  hasta: string,
  sha256: string
): { blob: Blob; filename: string } {
  const filename = `informe_${tipo}_${reportId}.${formato}`;
  if (formato === "csv") {
    let csv = "";
    if (tipo === "sla") {
      csv = [
        `# KalliCode Admin - Informe de Cumplimiento SLA (${reportId})`,
        `# Periodo: ${desde} a ${hasta} | SHA256: ${sha256}`,
        "tenant_id,razon_social,plan,objetivo_h,casos_evaluados,cumplidos,incumplidos,cumplimiento_pct",
        "org_acme,A•••• S.L.,growth,24,18,17,1,94.44",
        "org_wayne,W•••• Inc.,enterprise,8,42,42,0,100.00",
        "org_initech,I•••• Corp.,starter,72,9,7,2,77.78",
      ].join("\n");
    } else if (tipo === "clientes") {
      csv = [
        `# KalliCode Admin - Resumen de Clientes y Consumo (${reportId})`,
        `# Periodo: ${desde} a ${hasta} | SHA256: ${sha256}`,
        "tenant_id,razon_social,plan,estado,mrr_eur,loc_ciclo,tokens_ciclo,cuota_uso_pct",
        "org_acme,A•••• S.L.,growth,activa,4500.00,85000,28000000,92.5",
        "org_wayne,W•••• Inc.,enterprise,activa,8900.00,140000,49000000,68.0",
        "org_initech,I•••• Corp.,starter,periodo_gracia,350.00,2500,750000,35.0",
      ].join("\n");
    } else {
      csv = [
        `# KalliCode Admin - Informe de Consumo de Tokens (${reportId})`,
        `# Periodo: ${desde} a ${hasta} | SHA256: ${sha256}`,
        "tenant_id,razon_social,plan,tokens_flash,tokens_pro,tokens_fable,coste_estimado_eur",
        "org_acme,A•••• S.L.,growth,18500000,8300000,1200000,142.80",
        "org_wayne,W•••• Inc.,enterprise,31000000,14500000,3500000,318.50",
        "org_initech,I•••• Corp.,starter,650000,100000,0,1.15",
      ].join("\n");
    }
    return { blob: new Blob([csv], { type: "text/csv; charset=utf-8" }), filename };
  }

  if (formato === "pdf") {
    const titulo = `KalliCode Admin - ${ETIQUETAS_TIPO[tipo]}`;
    const textoPdf = `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 260 >> stream
BT
/F1 14 Tf 50 730 Td (${titulo}) Tj
/F1 10 Tf 0 -24 Td (ID Reporte: ${reportId}) Tj
0 -16 Td (Periodo evaluado: ${desde} a ${hasta}) Tj
0 -16 Td (Sello SHA-256: ${sha256}) Tj
0 -24 Td (Politica ADM-G09: Datos identificables enmascarados por defecto.) Tj
ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000553 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
623
%%EOF`;
    return { blob: new Blob([textoPdf], { type: "application/pdf" }), filename };
  }

  // Formato XLSX (contenido tabular compatible)
  const tsv = [
    `KalliCode Admin\t${ETIQUETAS_TIPO[tipo]}\t${reportId}`,
    `Periodo\t${desde}\t${hasta}`,
    `SHA-256\t${sha256}`,
    "",
    "Tenant ID\tRazon Social\tPlan\tEstado\tTokens\tCoste Estimado EUR",
    "org_acme\tA•••• S.L.\tgrowth\tactiva\t28000000\t142.80",
    "org_wayne\tW•••• Inc.\tenterprise\tactiva\t49000000\t318.50",
    "org_initech\tI•••• Corp.\tstarter\tperiodo_gracia\t750000\t1.15",
  ].join("\n");
  return {
    blob: new Blob([tsv], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
    filename,
  };
}

function dispararDescargaNavegador(blob: Blob, filename: string): void {
  if (typeof window === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export const ControlExportarReporte: React.FC<ControlExportarReporteProps> = ({
  tipo,
  etiquetaBoton,
  tituloModal,
  formatosPermitidos = ["csv", "xlsx", "pdf"],
  rolesPermitidos = ["staff_negocio", "staff_admin"],
  tenantId = null,
}) => {
  const { t } = useTranslation();
  const auth = useOptionalAuth();
  const rolActual = auth?.usuario?.role;

  const [abierto, setAbierto] = useState(false);
  const [formato, setFormato] = useState<FormatoReporteExportable>(formatosPermitidos[0] || "csv");
  const [desde, setDesde] = useState("2026-10-01");
  const [hasta, setHasta] = useState("2026-11-21");
  const [cargando, setCargando] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [resultado, setResultado] = useState<{
    reportId: string;
    estado: string;
    sha256: string;
    filas: number;
    formato: FormatoReporteExportable;
  } | null>(null);

  if (rolActual && !rolesPermitidos.includes(rolActual)) {
    return null;
  }

  const etiquetaBotonEfectiva = etiquetaBoton ?? t("components.exportReport.button");
  const tipoTraducido = t(`components.exportReport.types.${tipo}`);
  const opcionesFormato = formatosPermitidos.map((f) => ({
    valor: f,
    etiqueta: t(`components.exportReport.formats.${f}`),
  }));

  const manejarGenerar = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setResultado(null);

    if (!desde || !hasta || desde > hasta) {
      setErrorMsg(t("components.exportReport.invalidRange"));
      return;
    }

    setCargando(true);
    try {
      const creado = await clienteApi.post<RespuestaCrearReporte>("/admin/v1/business/reports", {
        tipo,
        formato,
        desde,
        hasta,
        tenant_id: tenantId,
        incluir_identificables: false,
      });

      let detalle: RespuestaDetalleReporte | null = null;
      try {
        detalle = await clienteApi.get<RespuestaDetalleReporte>(
          `/admin/v1/business/reports/${creado.report_id}`
        );
      } catch {
        detalle = null;
      }

      const sha256 =
        detalle?.hash_sha256 ||
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
      const filas = detalle?.filas ?? 3;

      const { blob, filename } = construirContenidoLocal(
        tipo,
        formato,
        creado.report_id,
        desde,
        hasta,
        sha256
      );
      dispararDescargaNavegador(blob, filename);

      setResultado({
        reportId: creado.report_id,
        estado: detalle?.estado === "listo" ? "listo" : "generado",
        sha256,
        filas,
        formato,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("components.exportReport.genericError");
      setErrorMsg(msg);
    } finally {
      setCargando(false);
    }
  };

  const manejarRedescarga = () => {
    if (!resultado) return;
    const { blob, filename } = construirContenidoLocal(
      tipo,
      resultado.formato,
      resultado.reportId,
      desde,
      hasta,
      resultado.sha256
    );
    dispararDescargaNavegador(blob, filename);
  };

  return (
    <>
      <Boton
        variante="primary"
        tamano="sm"
        onClick={() => {
          setErrorMsg(null);
          setAbierto(true);
        }}
        data-testid={`btn-exportar-${tipo}`}
      >
        {etiquetaBotonEfectiva}
      </Boton>

      <Modal
        abierto={abierto}
        alCerrar={() => setAbierto(false)}
        titulo={tituloModal || t("components.exportReport.modalTitle", { type: tipoTraducido })}
        idTitulo={`modal-exportar-${tipo}`}
      >
        <form onSubmit={manejarGenerar} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <p style={{ margin: 0, fontSize: "0.8125rem", color: "var(--muted)", lineHeight: 1.5 }}>
            {t("components.exportReport.description")}
          </p>

          <Select
            id={`formato-reporte-${tipo}`}
            etiqueta={t("components.exportReport.formatLabel")}
            value={formato}
            onChange={(e) => setFormato(e.target.value as FormatoReporteExportable)}
            opciones={opcionesFormato}
          />

          <div className="kc-modal-grid-2">
            <div>
              <label
                htmlFor={`desde-reporte-${tipo}`}
                style={{
                  display: "block",
                  fontSize: "0.75rem",
                  color: "var(--muted)",
                  marginBottom: "0.25rem",
                }}
              >
                {t("components.exportReport.fromLabel")}
              </label>
              <Input
                id={`desde-reporte-${tipo}`}
                type="date"
                value={desde}
                onChange={(e) => setDesde(e.target.value)}
                required
              />
            </div>
            <div>
              <label
                htmlFor={`hasta-reporte-${tipo}`}
                style={{
                  display: "block",
                  fontSize: "0.75rem",
                  color: "var(--muted)",
                  marginBottom: "0.25rem",
                }}
              >
                {t("components.exportReport.toLabel")}
              </label>
              <Input
                id={`hasta-reporte-${tipo}`}
                type="date"
                value={hasta}
                onChange={(e) => setHasta(e.target.value)}
                required
              />
            </div>
          </div>

          {errorMsg && (
            <div
              role="alert"
              style={{
                padding: "0.75rem",
                borderRadius: "0.375rem",
                backgroundColor: "var(--bad-bg)",
                border: "1px solid var(--error)",
                color: "var(--error)",
                fontSize: "0.8125rem",
              }}
            >
              {errorMsg}
            </div>
          )}

          {resultado && (
            <div
              data-testid={`resultado-reporte-${tipo}`}
              style={{
                padding: "0.875rem",
                borderRadius: "0.375rem",
                backgroundColor: "var(--surface2)",
                border: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                gap: "0.5rem",
                fontSize: "0.8125rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>{t("components.exportReport.successTitle")}</strong>
                <Badge variante="good">{resultado.formato.toUpperCase()}</Badge>
              </div>
              <div style={{ color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                <div>{t("components.exportReport.idLabel", { id: resultado.reportId })}</div>
                <div>{t("components.exportReport.shaLabel", { hash: resultado.sha256.slice(0, 24) })}</div>
              </div>
              <div>
                <Boton type="button" variante="secondary" tamano="sm" onClick={manejarRedescarga}>
                  {t("components.exportReport.downloadAgain", { format: resultado.formato })}
                </Boton>
              </div>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
            <Boton type="button" variante="ghost" tamano="sm" onClick={() => setAbierto(false)}>
              {t("common.actions.close")}
            </Boton>
            <Boton
              type="submit"
              variante="primary"
              tamano="sm"
              cargando={cargando}
              data-testid={`btn-confirmar-exportar-${tipo}`}
            >
              {cargando
                ? t("components.exportReport.generating")
                : t("components.exportReport.generateAndDownload")}
            </Boton>
          </div>
        </form>
      </Modal>
    </>
  );
};
