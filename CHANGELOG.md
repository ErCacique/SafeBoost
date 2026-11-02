# Changelog

Todos los cambios relevantes de WinTune se documentan aquí.

El formato sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Estructura del repositorio, `pyproject.toml` y dependencias fijadas.
- Catálogo declarativo `data/tweaks.json` (70 entradas en 3 niveles) y su esquema
  `data/tweaks.schema.json` con reglas de coherencia: las acciones irreversibles y los
  tweaks de riesgo alto nunca entran en perfiles automáticos.
- README interno con perfiles, tabla de tweaks y sección "Qué NO toca WinTune".
