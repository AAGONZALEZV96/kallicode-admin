.PHONY: up down sync lint format test test-int no-fuga load-test

# Levanta la infraestructura de datos local
up:
	docker compose up -d

# Detiene la infraestructura
down:
	docker compose down

# Sincroniza el entorno determinista
sync:
	uv sync --all-extras

# Ejecuta los linters y chequeos de tipos respetando el CI
lint:
	uv run ruff check .
	uv run black --check apps/ tests/
	uv run mypy apps/api/src apps/workers/src

# Chequeo estricto de tipos con mypy
types:
	uv run mypy apps/api/src apps/workers/src

# Aplica formato de código
format:
	uv run ruff format .
	uv run black .

# Pruebas unitarias (Rápidas, sin BD)
test:
	KC_ADMIN_TEST_DSN="postgresql://postgres:postgres@localhost:5433/kallicode_test" \
	KC_ADMIN_REDIS_URL="redis://localhost:6380/1" \
	uv run pytest -m "not integracion" -q --no-cov

# Pruebas de integración usando la BD aislada en el puerto 5433
test-int:
	KC_ADMIN_TEST_DSN="postgresql://postgres:postgres@localhost:5433/kallicode_test" \
	KC_ADMIN_REDIS_URL="redis://localhost:6380/1" \
	uv run pytest --cov-report=term-missing

# Verificación de no-fuga y permisos del rol de lectura (Ticket KC-ADM-B2-01)
no-fuga:
	KC_ADMIN_TEST_DSN="postgresql://postgres:postgres@localhost:5433/kallicode_test" \
	KC_ADMIN_REDIS_URL="redis://localhost:6380/1" \
	uv run pytest tests/test_no_leak.py -v --no-cov

# Pruebas de carga concurrente (50 VUs) y contención SECURITY DEFINER (Ticket KC-ADM-B6-07)
load-test:
	KC_ADMIN_TEST_DSN="postgresql://postgres:postgres@localhost:5433/kallicode_test" \
	KC_ADMIN_REDIS_URL="redis://localhost:6380/1" \
	uv run pytest tests/test_load_performance.py -v --no-cov
