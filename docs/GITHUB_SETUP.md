# Configuración de GitHub (repo privado, un solo mantenedor)

> Los planes y precios de GitHub cambian. Lo que sigue es lo vigente cuando se escribió;
> compruébalo en *Settings → Billing and plans* antes de decidir.

## Flujo de trabajo

1. Rama desde `main`: `feat/<tema>` o `fix/<tema>`.
2. Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/):
   `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `chore:`.
   Un `!` o un pie `BREAKING CHANGE:` implica versión mayor.
3. `git push -u origin feat/<tema>` y abrir un PR contra `main` (contra ti mismo). Así se
   ejecuta el CI completo antes de integrar.
4. Merge con **Squash and merge**. El título del PR, en formato Conventional Commit, será el
   commit de `main`.
5. Versionado [SemVer](https://semver.org/lang/es/): `fix` → parche, `feat` → menor,
   cambio incompatible → mayor.

Ajustes recomendados en *Settings → General → Pull Requests*: dejar solo **Allow squash
merging** y activar **Automatically delete head branches**.

## Protección de la rama `main`

### Si tu plan lo permite (GitHub Pro, Team o Enterprise)

En repos **privados**, las reglas de protección de rama y los *rulesets* solo se aplican con un
plan de pago. Para una cuenta personal basta GitHub Pro.

*Settings → Rules → Rulesets → New ruleset → New branch ruleset*:

| Opción | Valor |
|---|---|
| Enforcement status | Active |
| Target branches | Include default branch |
| Restrict deletions | ✅ |
| Block force pushes | ✅ |
| Require a pull request before merging | ✅, con **0** aprobaciones (no puedes aprobar tu propio PR) |
| Require status checks to pass | ✅ `Lint, catálogo y tests (Linux)`, `Tests con winreg nativo (Windows)` y `E2E aplicar y revertir (Windows real)` |
| Require branches to be up to date | ✅ |
| Bypass list | Vacía, o tu usuario solo para emergencias |

Los checks solo aparecen en el desplegable cuando el CI se ha ejecutado al menos una vez.

### Si estás en GitHub Free

Las reglas no se aplicarán en un repo privado. Hay que sustituirlas en local:

- `pre-commit` incluye el hook `no-commit-to-branch` en las fases **pre-commit** y
  **pre-push**: bloquea commits y pushes directos a `main` desde tu máquina.
  ```bash
  pre-commit install
  pre-commit install --hook-type pre-push
  ```
- Integra siempre mediante PR con el CI en verde. Es disciplina, no imposición: un
  `git push --no-verify` se salta el hook.
- Si en algún momento haces el repo público, las reglas pasan a ser gratuitas: actívalas en
  ese momento.

## Escaneo de secretos y push protection

- **Secret scanning y push protection de GitHub** en repos **privados** forman parte de
  *GitHub Secret Protection*, que se contrata para organizaciones con plan Team o Enterprise
  (de pago, por committer). En una cuenta personal no están disponibles para repos privados.
- El ajuste personal *Settings → Code security → Push protection for yourself* solo cubre
  pushes a repos **públicos**.
- **Lo que sí está activo en este repo, gratis:**
  - `gitleaks` como hook de pre-commit: bloquea el commit si detecta un secreto.
  - `gitleaks` en el job de Linux del CI: analiza todo el historial en cada PR.
  - `detect-private-key` de pre-commit-hooks.
  - `.gitignore` excluye `.env*`, `*.pfx` y `*.p12`.
- **Si el repo se hace público:** *Settings → Advanced Security* → activar **Secret
  Protection** y **Push protection**, que son gratuitos en repos públicos.

Activa también, gratis en repos privados, en *Settings → Advanced Security*: **Dependency
graph**, **Dependabot alerts** y **Dependabot security updates**. `.github/dependabot.yml` ya
agrupa las actualizaciones semanales para minimizar PRs y ejecuciones.

## Consumo de minutos de Actions

- El job de Linux (lint, catálogo, tests y gitleaks) tarda unos 1-2 minutos.
- El job de Windows solo corre si el de Linux pasa, y solo ejecuta los tests de `winreg`.
- El job `e2e` (Windows, ~2-3 min) solo corre si el anterior pasa: aplica y revierte tweaks
  reales en la VM del runner. Es el único que comprueba WinTune contra Windows de verdad en
  cada PR; si los minutos aprietan, se puede limitar a `push` en `main`.
  Los minutos de Windows cuentan con multiplicador respecto a Linux en el cómputo de minutos
  incluidos.
- `concurrency` con `cancel-in-progress` cancela ejecuciones obsoletas de la misma rama.
- Los cambios que solo tocan `**.md` o `docs/**` en `main` no lanzan el CI.
- `release.yml` solo corre con un tag `v*.*.*` o a mano.

## Publicar una versión

```bash
# 1. En main actualizado, con el CI en verde
git checkout main && git pull origin main

# 2. Subir la versión en los TRES sitios (release.yml falla si no coinciden):
#    core/constants.py (APP_VERSION), pyproject.toml (version), packaging/version_info.txt
# 3. CHANGELOG.md: mover [Unreleased] a [X.Y.Z] - AAAA-MM-DD
git checkout -b chore/release-vX.Y.Z
git commit -am "chore(release): vX.Y.Z"
git push -u origin chore/release-vX.Y.Z      # PR → CI → squash merge

# 4. Tag sobre main ya integrado
git checkout main && git pull origin main
git tag -a vX.Y.Z -m "WinTune vX.Y.Z"
git push origin vX.Y.Z                         # dispara release.yml
```

**Alternativa sin crear el tag en local:** *Actions → Release → Run workflow* sobre `main`
con `tag = vX.Y.Z`. El workflow compila y crea el tag y el Release en esa misma ejecución.
Con `tag` vacío solo compila y deja el `.exe` como artifact.

`release.yml` compila en `windows-latest` y ejecuta `WinTune.exe --self-test`. Después
calcula el SHA256 y publica el `.exe` y el `.sha256` como assets del Release y como artifact.

## Pendiente si el repo se hace público

- `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md` y plantillas de issues y PR.
- Activar Secret Protection, push protection y las reglas de rama, que pasan a ser gratuitos.
- Revisar el historial en busca de datos personales o rutas locales.
