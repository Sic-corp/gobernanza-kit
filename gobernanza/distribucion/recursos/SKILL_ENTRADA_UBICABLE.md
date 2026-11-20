---
name: gobernanza-local
description: Localizar el procedimiento de la versión del kit instalada en este repositorio.
---

# Entrada al procedimiento local

Identifica la raíz Git del consumidor y lee el bloque gestionado de
`AGENTS.md`. En modo ubicable, `activo.json` vive junto al administrador
`gestionar.py` indicado allí. Las instalaciones estándar y aisladas usan
el selector `.gobernanza-kit/activo.json` desde la raíz del consumidor.

El campo `huella_paquete` del selector identifica el slot
`versiones/<huella_paquete>/` junto al selector. Dentro del slot sigue
`contenido/skill/SKILL.md`, con las referencias de esa versión. Consulta
el estado y la recuperación en el administrador local del consumidor.
