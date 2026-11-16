## Table `plans`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `codigo` | `text` | Primary |
| `nombre` | `text` |  |
| `lineas` | `int4` |  Nullable |
| `loc_mes` | `int4` |  Nullable |
| `max_usuarios` | `int4` |  Nullable |
| `storage_mb` | `int4` |  Nullable |
| `docs_mb` | `int4` |  Nullable |
| `permite_help` | `bool` |  |
| `despliegues` | `_text` |  |
| `creado_en` | `timestamptz` |  |

## Table `schema_migrations`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `archivo` | `text` | Primary |
| `sha256` | `text` |  |
| `aplicado_en` | `timestamptz` |  |
| `duracion_ms` | `int4` |  |

## Table `organizations`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `nombre` | `text` |  |
| `idioma` | `text` |  |
| `timezone` | `text` |  |
| `despliegue` | `text` |  |
| `fabrica_activa` | `bool` |  |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |
| `eliminado_en` | `timestamptz` |  Nullable |

## Table `subscriptions`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `plan_codigo` | `text` |  |
| `estado` | `text` |  |
| `inicia_el` | `date` |  |
| `renueva_el` | `date` |  |
| `finaliza_el` | `date` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `users`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `email` | `text` |  |
| `nombre` | `text` |  |
| `rol` | `text` |  |
| `estado` | `text` |  |
| `idioma` | `text` |  |
| `password_hash` | `text` |  Nullable |
| `notificaciones` | `jsonb` |  |
| `ultimo_acceso` | `timestamptz` |  Nullable |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `invitations`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `email` | `text` |  |
| `rol` | `text` |  |
| `token_hash` | `text` |  Unique |
| `invitado_por` | `text` |  |
| `estado` | `text` |  |
| `expira_en` | `timestamptz` |  |
| `usado_en` | `timestamptz` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `refresh_tokens`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `user_id` | `text` |  |
| `token_hash` | `text` |  Unique |
| `emitido_en` | `timestamptz` |  |
| `expira_en` | `timestamptz` |  |
| `usado_en` | `timestamptz` |  Nullable |
| `revocado` | `bool` |  |
| `ip` | `inet` |  Nullable |
| `user_agent` | `text` |  Nullable |

## Table `password_reset_tokens`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `user_id` | `text` |  |
| `token_hash` | `text` |  Unique |
| `expira_en` | `timestamptz` |  |
| `usado_en` | `timestamptz` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `production_lines`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `numero` | `int4` | Primary |
| `estado` | `text` |  |
| `job_id` | `text` |  Nullable |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `ticket_counters`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `ultimo` | `int4` |  |

## Table `tickets`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `numero` | `text` |  Nullable |
| `tipo` | `text` |  |
| `titulo` | `text` |  |
| `descripcion` | `text` |  |
| `prioridad` | `text` |  |
| `prioridad_pipeline` | `text` |  Nullable |
| `etapa` | `text` |  |
| `gate_pendiente` | `int2` |  Nullable |
| `origen` | `text` |  |
| `origen_ref` | `jsonb` |  Nullable |
| `reportado_por` | `text` |  Nullable |
| `usuario_final` | `jsonb` |  Nullable |
| `modulo_pista` | `text` |  Nullable |
| `duplicado_de` | `text` |  Nullable |
| `impacto` | `jsonb` |  Nullable |
| `complejidad` | `text` |  Nullable |
| `pr_url` | `text` |  Nullable |
| `fecha_objetivo` | `date` |  Nullable |
| `motivo_cancelacion` | `text` |  Nullable |
| `cancelado_por` | `text` |  Nullable |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |
| `cerrado_en` | `timestamptz` |  Nullable |

## Table `ticket_attachments`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  Nullable |
| `nombre_archivo` | `text` |  |
| `content_type` | `text` |  |
| `tamano_bytes` | `int8` |  |
| `blob_ref` | `text` |  |
| `clase` | `text` |  |
| `escaneo` | `text` |  |
| `subido_por` | `text` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `ticket_watchers`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` |  |
| `ticket_id` | `text` | Primary |
| `user_id` | `text` | Primary |
| `creado_en` | `timestamptz` |  |

## Table `specs`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `version` | `int4` |  |
| `estado` | `text` |  |
| `spec_md_ref` | `text` |  |
| `scope_paths` | `_text` |  |
| `plan_tests` | `jsonb` |  Nullable |
| `migraciones` | `jsonb` |  Nullable |
| `adr_borrador` | `jsonb` |  Nullable |
| `estimacion_loc` | `int4` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `spec_alternatives`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `spec_id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `alt_id` | `text` | Primary |
| `titulo` | `text` |  |
| `descripcion` | `text` |  |
| `riesgo` | `text` |  |
| `recomendada` | `bool` |  |
| `elegida` | `bool` |  |

## Table `spec_criteria`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `spec_id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `criterio_id` | `text` | Primary |
| `given_txt` | `text` |  |
| `when_txt` | `text` |  |
| `then_txt` | `text` |  |

## Table `jobs`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `estado` | `text` |  |
| `linea` | `int4` |  Nullable |
| `prioridad` | `text` |  |
| `iteraciones` | `jsonb` |  |
| `contexto` | `jsonb` |  Nullable |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |
| `terminado_en` | `timestamptz` |  Nullable |

## Table `job_transitions`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int8` | Primary Identity |
| `tenant_id` | `text` |  |
| `job_id` | `text` |  |
| `de_estado` | `text` |  |
| `a_estado` | `text` |  |
| `motivo` | `text` |  Nullable |
| `contexto` | `jsonb` |  Nullable |
| `actor` | `text` |  |
| `creado_en` | `timestamptz` | Primary |

## Table `llm_steps`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `job_id` | `text` |  |
| `ticket_id` | `text` |  |
| `etapa` | `text` |  |
| `paso` | `text` |  |
| `version_plantilla` | `text` |  |
| `modelo` | `text` |  |
| `tier` | `text` |  |
| `confianza` | `numeric` |  Nullable |
| `validacion` | `text` |  |
| `reintentos` | `int2` |  |
| `tokens_in` | `int4` |  |
| `tokens_out` | `int4` |  |
| `duracion_ms` | `int4` |  |
| `entrada_ref` | `text` |  |
| `salida_ref` | `text` |  |
| `creado_en` | `timestamptz` |  |

## Table `gate_signatures`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `gate` | `int2` |  |
| `accion` | `text` |  |
| `actor_id` | `text` |  |
| `comentario` | `text` |  Nullable |
| `alternativa_id` | `text` |  Nullable |
| `acepta_fallos` | `bool` |  |
| `devolver_a` | `text` |  Nullable |
| `spec_id` | `text` |  Nullable |
| `sello` | `text` |  |
| `creado_en` | `timestamptz` |  |

## Table `qa_runs`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `spec_id` | `text` |  |
| `corrida` | `int4` |  |
| `regresion` | `jsonb` |  |
| `flaky` | `jsonb` |  |
| `ejecutada_en` | `timestamptz` |  |

## Table `qa_results`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `qa_run_id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `criterio_id` | `text` | Primary |
| `resultado` | `text` |  |
| `extracto_fallo` | `text` |  Nullable |
| `veredicto_visual` | `jsonb` |  Nullable |
| `evidencias` | `jsonb` |  |

## Table `security_findings`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `origen` | `text` |  |
| `regla` | `text` |  Nullable |
| `archivo` | `text` |  Nullable |
| `linea` | `int4` |  Nullable |
| `severidad` | `text` |  |
| `titulo` | `text` |  |
| `veredicto` | `text` |  |
| `justificacion` | `text` |  Nullable |
| `fix_diff_ref` | `text` |  Nullable |
| `bloquea` | `bool` |  |
| `estado` | `text` |  |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `usage_tokens`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int8` | Primary Identity |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  |
| `etapa` | `text` |  |
| `modelo` | `text` |  |
| `tier` | `text` |  |
| `invocaciones` | `int4` |  |
| `tokens_in` | `int4` |  |
| `tokens_out` | `int4` |  |
| `duracion_ms` | `int4` |  |
| `creado_en` | `timestamptz` | Primary |

## Table `usage_loc`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int8` | Primary Identity |
| `tenant_id` | `text` |  |
| `ticket_id` | `text` |  Nullable |
| `ciclo` | `text` |  |
| `tipo` | `text` |  |
| `pr_url` | `text` |  Nullable |
| `anadidas` | `int4` |  |
| `eliminadas` | `int4` |  |
| `netas` | `int4` |  |
| `tests` | `int4` |  |
| `motivo_ajuste` | `text` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `usage_cycles`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `ciclo` | `text` | Primary |
| `loc_consumidas` | `int4` |  |
| `umbral` | `text` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `connections`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `categoria` | `text` |  |
| `proveedor` | `text` |  |
| `nombre` | `text` |  Nullable |
| `config` | `jsonb` |  |
| `secreto_ref` | `text` |  Nullable |
| `ruta_token` | `text` |  Nullable Unique |
| `estado` | `text` |  |
| `ultimo_test` | `timestamptz` |  Nullable |
| `ultimo_test_detalle` | `jsonb` |  Nullable |
| `creado_en` | `timestamptz` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `branch_map`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `feature_pattern` | `text` |  |
| `staging_branch` | `text` |  |
| `prod_branch` | `text` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `webhook_inbox`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int8` | Primary Identity |
| `tenant_id` | `text` |  |
| `connection_id` | `text` |  |
| `delivery_id` | `text` |  |
| `evento` | `text` |  Nullable |
| `payload` | `jsonb` |  |
| `estado` | `text` |  |
| `error_detalle` | `text` |  Nullable |
| `ticket_id` | `text` |  Nullable |
| `recibido_en` | `timestamptz` | Primary |
| `procesado_en` | `timestamptz` |  Nullable |

## Table `model_providers`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `proveedor` | `text` | Primary |
| `llave_ref` | `text` |  Nullable |
| `llave_mascara` | `text` |  Nullable |
| `base_url` | `text` |  Nullable |
| `estado` | `text` |  |
| `modelos_disponibles` | `jsonb` |  |
| `ultimo_test` | `timestamptz` |  Nullable |
| `actualizado_en` | `timestamptz` |  |

## Table `model_assignments`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `tenant_id` | `text` | Primary |
| `funcion` | `text` | Primary |
| `principal_proveedor` | `text` |  |
| `principal_modelo` | `text` |  |
| `fallback_proveedor` | `text` |  |
| `fallback_modelo` | `text` |  |
| `actualizado_en` | `timestamptz` |  |

## Table `notifications`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `user_id` | `text` |  |
| `tipo` | `text` |  |
| `titulo` | `text` |  |
| `cuerpo` | `text` |  Nullable |
| `ticket_id` | `text` |  Nullable |
| `leida` | `bool` |  |
| `creada_en` | `timestamptz` | Primary |

## Table `idempotency_keys`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `clave` | `text` | Primary |
| `tenant_id` | `text` | Primary |
| `endpoint` | `text` | Primary |
| `respuesta` | `jsonb` |  |
| `status_code` | `int2` |  |
| `creado_en` | `timestamptz` |  |

## Table `escalations`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `job_id` | `text` |  |
| `etapa` | `text` |  |
| `paso` | `text` |  Nullable |
| `motivo` | `text` |  |
| `severidad` | `text` |  |
| `detalle` | `jsonb` |  |
| `estado` | `text` |  |
| `resuelto_por` | `text` |  Nullable |
| `resuelto_en` | `timestamptz` |  Nullable |
| `creado_en` | `timestamptz` |  |

## Table `audit_exports`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `formato` | `text` |  |
| `ticket_id` | `text` |  Nullable |
| `filtros` | `jsonb` |  Nullable |
| `estado` | `text` |  |
| `blob_ref` | `text` |  Nullable |
| `solicitado_por` | `text` |  |
| `creado_en` | `timestamptz` |  |
| `completado_en` | `timestamptz` |  Nullable |

## Table `onboarding_documents`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `nombre_archivo` | `text` |  |
| `content_type` | `text` |  |
| `tamano_bytes` | `int8` |  |
| `tipo_documento` | `text` |  |
| `blob_ref` | `text` |  |
| `hash_contenido` | `text` |  Nullable |
| `estado` | `text` |  |
| `subido_por` | `text` |  |
| `creado_en` | `timestamptz` |  |

## Table `upgrade_requests`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `text` | Primary |
| `tenant_id` | `text` |  |
| `plan_deseado` | `text` |  |
| `comentario` | `text` |  Nullable |
| `urgente` | `bool` |  |
| `estado` | `text` |  |
| `solicitado_por` | `text` |  |
| `creado_en` | `timestamptz` |  |

## RLS Policies

### `subscriptions`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `organizations`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(id = core.current_tenant())` | `(id = core.current_tenant())` |

### `users`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `invitations`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `refresh_tokens`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `password_reset_tokens`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `production_lines`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `ticket_counters`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `tickets`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `ticket_attachments`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `ticket_watchers`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `specs`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `spec_alternatives`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `spec_criteria`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `jobs`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `job_transitions`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `llm_steps`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `gate_signatures`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `qa_runs`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `qa_results`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `security_findings`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `usage_tokens`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `usage_loc`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `usage_cycles`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `connections`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `branch_map`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `webhook_inbox`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `model_providers`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `model_assignments`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `notifications`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `idempotency_keys`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `escalations`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `audit_exports`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `onboarding_documents`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

### `upgrade_requests`

| Policy | Command | Roles | Action | USING | WITH CHECK |
|--------|---------|-------|--------|-------|------------|
| `tenant_isolation` | ALL | public | PERMISSIVE | `(tenant_id = core.current_tenant())` | `(tenant_id = core.current_tenant())` |

