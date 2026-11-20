---
name: gobernanza-local
description: Retomar, planificar, construir y cerrar trabajo acordado con el kit local instalado en este consumidor, conservando pruebas y guardados.
---

# Entrada al procedimiento de gobernanza instalado

Esta entrada estable pertenece al consumidor. Identifica `raiz_trabajo` tres
directorios por encima de esta carpeta de skill y lee el
[selector local](../../../.gobernanza-kit/activo.json). Su `huella_paquete` identifica
el slot `.gobernanza-kit/versiones/<huella_paquete>/` dentro de esa misma raíz.

Lee allí `contenido/skill/SKILL.md`, que contiene el procedimiento completo y
referencias relativas de la versión activa. El manifiesto del slot conserva
versión, commit fuente e inventario; no necesitas el repositorio autor ni red.
No deduzcas la versión por el nombre de una rama ni reconstruyas documentación
desde una ruta fuente antigua.

Si existe `.gobernanza-kit/transaccion.json`, conserva el estado y usa el
administrador local para inspeccionar o recuperar antes de construir. El arranque
normal rechaza esa situación. El procedimiento no concede una autorización nueva:
lee AGENTS, continuidad y acuerdo real de la sesión aplicable.
