/**
 * Suite de pruebas de carga con k6 — Consola de Administración KalliCode (KC-ADM-B6-07)
 *
 * Evalúa el rendimiento de los endpoints analíticos cross-tenant y la contención
 * en PostgreSQL frente a los refrescos periódicos ejecutados por funciones
 * SECURITY DEFINER (admin.refresh_* / rol kallicode_admin_agg).
 *
 * Escenarios:
 *   1. escenario_1_agregados_negocio: rampa hasta 50 VUs concurrentes sobre
 *      /admin/v1/business/summary, /overview, /customers y /usage/tokens.
 *   2. escenario_2_ops_polling: polling concurrente de operadores con ventana
 *      activa sobre /admin/v1/ops/agents, /ops/models y /ops/sla.
 *   3. escenario_3_lectura_bajo_refresco_secdef: lecturas continuas + sonda
 *      /admin/v1/health mientras el worker recalcula vistas y agregados.
 *
 * SLOs / Thresholds innegociables:
 *   - Latencia p95 < 500 ms bajo 50 consultas concurrentes.
 *   - Tasa de error HTTP 5xx < 1% (objetivo 0%).
 *   - Tasa de éxito de checks (HTTP 200 + validación JSON) >= 99%.
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.K6_BASE_URL || 'http://localhost:8000';
const CICLO_ACTUAL = __ENV.K6_CICLO || new Date().toISOString().slice(0, 7);
// Si el servicio de telemetría de E2 aún no está levantado en el entorno local,
// permite validar tanto el camino 200 (con stub E2) como la degradación controlada
// del circuit breaker (503 TELEMETRIA_NO_DISPONIBLE en < 500 ms) sin falsos fallos.
const TELEMETRIA_E2_ACTIVA = (__ENV.K6_TELEMETRY_E2_ACTIVE || 'true') === 'true';

// Métricas personalizadas por dominio y control de errores 5xx
const adminServerErrors = new Rate('admin_server_errors');
const latenciaNegocioMs = new Trend('latencia_negocio_ms', true);
const latenciaOpsMs = new Trend('latencia_ops_ms', true);
const latenciaSlaMs = new Trend('latencia_sla_ms', true);

// Pool de 50 tokens JWT de staff (uno por VU) para no disparar artificialmente
// el rate limit por empleado (RL-4: 300 req/min y limite_vivo: 60 req/min).
const staffTokens = new SharedArray('staff_tokens', function () {
  if (__ENV.K6_STAFF_TOKENS_JSON) {
    return JSON.parse(__ENV.K6_STAFF_TOKENS_JSON);
  }
  try {
    const raw = open('./tokens.json');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
  } catch (_) {
    // Fallback a token único de entorno cuando no existe tokens.json en disco
  }
  return [__ENV.K6_ADMIN_TOKEN || 'token-local-no-definido'];
});

export const options = {
  scenarios: {
    escenario_1_agregados_negocio: {
      executor: 'ramping-vus',
      exec: 'escenarioAgregadosNegocio',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 20 },
        { duration: '25s', target: 50 },
        { duration: '60s', target: 50 },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '5s',
      tags: { escenario: 'negocio', tipo: 'admin_api' },
    },
    escenario_2_ops_polling: {
      executor: 'ramping-vus',
      exec: 'escenarioOpsPolling',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 15 },
        { duration: '25s', target: 30 },
        { duration: '60s', target: 30 },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '5s',
      tags: { escenario: 'ops', tipo: 'admin_api' },
    },
    escenario_3_lectura_bajo_refresco_secdef: {
      executor: 'ramping-vus',
      exec: 'escenarioLecturaBajoRefresco',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 10 },
        { duration: '25s', target: 20 },
        { duration: '60s', target: 20 },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '5s',
      tags: { escenario: 'secdef_contention', tipo: 'admin_api' },
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<900'],
    'http_req_duration{escenario:negocio}': ['p(95)<500', 'p(99)<800'],
    'http_req_duration{escenario:ops}': ['p(95)<500', 'p(99)<850'],
    'http_req_duration{escenario:secdef_contention}': ['p(95)<500', 'p(99)<900'],
    http_req_failed: ['rate<0.01'],
    admin_server_errors: ['rate<0.01'],
    checks: ['rate>=0.99'],
    latencia_negocio_ms: ['p(95)<500'],
    latencia_ops_ms: ['p(95)<500'],
    latencia_sla_ms: ['p(95)<500'],
  },
};

function headersForVU() {
  const idx = ((__VU || 1) - 1) % staffTokens.length;
  return {
    headers: {
      Authorization: `Bearer ${staffTokens[idx]}`,
      Accept: 'application/json',
      Host: __ENV.K6_HOST_HEADER || 'localhost',
    },
  };
}

function parseJsonSafe(res) {
  try {
    return res.json();
  } catch (_) {
    return null;
  }
}

export function escenarioAgregadosNegocio() {
  const params = headersForVU();

  group('Negocio · Agregados Cross-Tenant (50 VUs)', function () {
    const rSum = http.get(`${BASE_URL}/admin/v1/business/summary`, params);
    adminServerErrors.add(rSum.status >= 500);
    latenciaNegocioMs.add(rSum.timings.duration);
    check(rSum, {
      'business/summary status 200': (r) => r.status === 200,
      'business/summary payload valido': (r) => {
        const b = parseJsonSafe(r);
        return b !== null && typeof b === 'object' && 'frescura' in b;
      },
    });

    const rOvw = http.get(
      `${BASE_URL}/admin/v1/business/overview?periodo=mes_actual&comparar_con=periodo_anterior`,
      params
    );
    adminServerErrors.add(rOvw.status >= 500);
    latenciaNegocioMs.add(rOvw.timings.duration);
    check(rOvw, {
      'business/overview status 200': (r) => r.status === 200,
      'business/overview contiene clientes e ingreso': (r) => {
        const b = parseJsonSafe(r);
        return b !== null && 'clientes' in b && 'ingreso_recurrente' in b;
      },
    });

    const rCust = http.get(
      `${BASE_URL}/admin/v1/business/customers?page=1&page_size=25`,
      params
    );
    adminServerErrors.add(rCust.status >= 500);
    latenciaNegocioMs.add(rCust.timings.duration);
    check(rCust, {
      'business/customers status 200': (r) => r.status === 200,
      'business/customers devuelve items paginados': (r) => {
        const b = parseJsonSafe(r);
        return b !== null && Array.isArray(b.items) && typeof b.total === 'number';
      },
    });

    const rTok = http.get(
      `${BASE_URL}/admin/v1/business/usage/tokens?periodo=mes_actual&agrupar_por=cliente`,
      params
    );
    adminServerErrors.add(rTok.status >= 500);
    latenciaNegocioMs.add(rTok.timings.duration);
    check(rTok, {
      'business/usage/tokens status 200': (r) => r.status === 200,
      'business/usage/tokens devuelve items y frescura': (r) => {
        const b = parseJsonSafe(r);
        return b !== null && Array.isArray(b.items) && 'frescura' in b;
      },
    });
  });

  sleep(0.8);
}

export function escenarioOpsPolling() {
  const params = headersForVU();

  group('Operaciones · Live Refresh Polling', function () {
    const rAg = http.get(`${BASE_URL}/admin/v1/ops/agents?ventana=1h`, params);
    const agDegradadoEsperado = !TELEMETRIA_E2_ACTIVA && rAg.status === 503;
    adminServerErrors.add(rAg.status >= 500 && !agDegradadoEsperado);
    latenciaOpsMs.add(rAg.timings.duration);
    check(rAg, {
      'ops/agents status 200 o degradacion controlada sin E2': (r) =>
        r.status === 200 || agDegradadoEsperado,
      'ops/agents payload coherente': (r) => {
        const b = parseJsonSafe(r);
        if (r.status === 200) {
          return b !== null && 'lineas' in b && 'telemetria' in b;
        }
        return b !== null && b.error && b.error.codigo === 'TELEMETRIA_NO_DISPONIBLE';
      },
    });

    const rMod = http.get(`${BASE_URL}/admin/v1/ops/models?ventana=24h`, params);
    const modDegradadoEsperado = !TELEMETRIA_E2_ACTIVA && rMod.status === 503;
    adminServerErrors.add(rMod.status >= 500 && !modDegradadoEsperado);
    latenciaOpsMs.add(rMod.timings.duration);
    check(rMod, {
      'ops/models status 200 o degradacion controlada sin E2': (r) =>
        r.status === 200 || modDegradadoEsperado,
      'ops/models payload coherente': (r) => {
        const b = parseJsonSafe(r);
        if (r.status === 200) {
          return b !== null && Array.isArray(b.proveedores) && Array.isArray(b.modelos);
        }
        return b !== null && b.error && b.error.codigo === 'TELEMETRIA_NO_DISPONIBLE';
      },
    });

    const rSla = http.get(
      `${BASE_URL}/admin/v1/ops/sla?ciclo=${CICLO_ACTUAL}`,
      params
    );
    adminServerErrors.add(rSla.status >= 500);
    latenciaSlaMs.add(rSla.timings.duration);
    check(rSla, {
      'ops/sla status 200 (100% SQL propio sin depender de E2)': (r) => r.status === 200,
      'ops/sla incluye resumen, por_plan e items': (r) => {
        const b = parseJsonSafe(r);
        return b !== null && 'resumen' in b && 'por_plan' in b && Array.isArray(b.items);
      },
    });
  });

  // Pacing de 2.5s por operador para respetar limite_vivo (60 req/min por staff_id)
  sleep(2.5);
}

export function escenarioLecturaBajoRefresco() {
  const params = headersForVU();

  group('Contención SECURITY DEFINER · Lectura bajo Refresco', function () {
    const rHealth = http.get(`${BASE_URL}/admin/v1/health`, params);
    adminServerErrors.add(rHealth.status >= 500);
    check(rHealth, {
      'health status 200 durante refresco': (r) => r.status === 200,
      'health dependencias postgres y lectura ok': (r) => {
        const b = parseJsonSafe(r);
        return (
          b !== null &&
          b.dependencias &&
          b.dependencias.postgres === true &&
          b.dependencias.lectura_analitica === true
        );
      },
    });

    const rSla = http.get(
      `${BASE_URL}/admin/v1/ops/sla?ciclo=${CICLO_ACTUAL}`,
      params
    );
    adminServerErrors.add(rSla.status >= 500);
    latenciaSlaMs.add(rSla.timings.duration);
    check(rSla, {
      'ops/sla 200 durante refresh_sla': (r) => r.status === 200,
    });

    const rCust = http.get(
      `${BASE_URL}/admin/v1/business/customers?page=1&page_size=25`,
      params
    );
    adminServerErrors.add(rCust.status >= 500);
    latenciaNegocioMs.add(rCust.timings.duration);
    check(rCust, {
      'business/customers 200 durante refresh_all': (r) => r.status === 200,
    });
  });

  sleep(1.0);
}
