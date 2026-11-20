# Distribución e instalación local

El kit requiere POSIX, Git y Python 3.10 o posterior. La instalación pertenece
al repositorio consumidor y su modalidad queda registrada en `AGENTS.md`.
Los comandos de descarga son explícitos y la instalación sigue siendo local.

## Bootstrap de una release

Ejecuta el bootstrap desde la raíz Git del consumidor. En Bash o Zsh,
`pipefail` hace que el bloque devuelva un error si falla `curl`.

```bash
(
  set -o pipefail
  curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- instalar
)
```

En un shell POSIX, descarga el script completo y ejecútalo después de que
`curl` termine correctamente.

```sh
kit=$(curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh) &&
  printf '%s\n' "$kit" | sh -s -- instalar
```

Para una instalación existente, usa el verbo `actualizar` en el comando
correspondiente. Usa `--raiz R` para actuar sobre otra raíz Git.
`--version V3.02` selecciona una release y `--solo-plan` permite inspeccionar
el cambio antes de aplicar.
El bootstrap contrasta la huella del ZIP completo y usa el instalador que
contiene. Para conectar la huella con una publicación concreta, revisa
`manifiesto.json`. Allí constan la V, el SHA del commit público y el SHA-256 de
los activos.

El lanzador instalado en la raíz del proyecto admite `./gobernanza-kit actualizar`
sin localizar a mano el slot activo. Usa `./gobernanza-kit actualizar --help`
para consultar sus opciones y la guía instalada para la CLI de trabajo.

## Adoptar el kit en un repositorio existente

El corte de adopción fija desde qué commit y para qué trabajo rige el nuevo
flujo. Empieza por una capacidad que el equipo vaya a mantener o cambiar
pronto. Usa ese caso para acordar las rutas, comprobar el recorrido y decidir
qué más conviene incorporar.

### 1. Fijar la línea base y el trabajo en curso

1. En la raíz Git del consumidor, registra el SHA completo de la rama de
   integración que usarás como base, el estado del árbol y las ramas o
   worktrees con trabajo abierto. Anota por cada trabajo su responsable, ref
   o cambio local, autoridad vigente y comprobaciones pendientes. Prepara la
   adopción en un worktree propio a partir de la base acordada.
2. Ejecuta la compilación y las pruebas habituales del consumidor sobre esa
   base. Guarda el SHA, comandos, entorno y resultados reales. Distingue los
   fallos que ya existían y las comprobaciones pendientes de las regresiones
   que aparezcan durante la adopción.
3. Acuerda el punto de entrada al flujo nuevo. Para cada rama en curso,
   decide si termina con su proceso vigente o si se releva al kit desde un
   commit concreto. Registra qué flujo autoriza los guardados y el cierre.
   Si ambos flujos conviven, coordina las rutas que toca cada rama y
   concilia la base y los contratos al integrar.

### 2. Asignar las rutas por responsabilidad

Haz un inventario con la ruta actual, su dueño y el uso que tendrá después
del corte. Declara prefijos concretos y comprueba que los destinos de
evidencia queden fuera de las rutas de código, pruebas y controles.

| Qué contiene | Dónde se conserva o registra |
|---|---|
| Código, recursos y migraciones de la aplicación | Sus rutas actuales, por ejemplo `src/` o `apps/`. Declara las rutas que gobiernas en `raices.solucion` de `gobernanza/config.json`. |
| Pruebas y fixtures | Sus rutas actuales, por ejemplo `tests/`. Incluye en `raices.pruebas` los archivos y directorios que gobernará el kit. El inventario de `unittest` exige vincular al criterio cada caso que detecte en esas rutas. Conserva la suite completa en el runner del proyecto. |
| Controles del repositorio | `AGENTS.md`, CI, hooks y configuración, según su dueño. Declara los controles que gobiernas en `raices.controles`. El gestor administra su bloque delimitado de `AGENTS.md`. |
| Documentación de producto, decisiones y backlog | Conserva sus fuentes vigentes, por ejemplo `docs/` y el gestor de incidencias. Reserva los patrones de `documentos` para el inventario mecánico con cabecera JSON. |
| Contratos y sesiones tipificados | `sdd/registro/` para los registros, `sdd/operaciones/` para los recibos, `sdd/aprobaciones/` para las aprobaciones de arranque cuando correspondan y `sdd/indice.md` para el índice generado. |
| Resultados y guardados | Conserva las referencias originales a CI e informes históricos. Para las sesiones gobernadas usa `sesiones/estado/` y los destinos acordados de evidencia, por defecto `sesiones/evidencias/`. |
| Motor y documentación instalada | Según el modo de instalación. El mapa de modo ubicable asigna la raíz del kit. Las rutas de la aplicación y del registro se resuelven desde la raíz Git del consumidor. |

Revisa los destinos de la instalación y del registro por separado, incluidos
archivos ignorados, enlaces y usos anteriores de las rutas SDD en Git. Si
`gobernanza/config.json` ya existe, comprueba que sea compatible con el
esquema 1. Un `sdd/indice.md` ajeno o un historial previo en las rutas del
registro requieren conciliación antes de activar el SDD. El registro coteja
la historia Git de sus operaciones. Si hay una colisión sin resolver, limita
la adopción a los pasos compatibles y deja asentado el impedimento.

### 3. Ensayar la instalación y configurar el consumidor

| Modalidad | Cuándo elegirla |
|---|---|
| Estándar | El plan puede usar `.gobernanza-kit/`, el puente Python `gobernanza/__init__.py` y `.agents/skills/gobernanza-local/SKILL.md`. |
| Aislada | El proyecto ya tiene un paquete Python `gobernanza`. Usa el gestor bajo `.gobernanza-kit/` y la misma ruta de skill que el modo estándar. |
| Ubicable | La instalación necesita una raíz distinta, por ejemplo si la ruta de skill ya tiene otro dueño. Declara una ruta relativa libre en `gobernanza/rutas-kit.json` para alojar allí el gestor, la skill y el paquete. |

Los tres modos de la entrega actual comprueban también `./gobernanza-kit` y
el bloque de `AGENTS.md`. Si el plan detecta contenido ajeno o una
instalación anterior, revisa su procedencia y decide la adecuación con el
dueño. Para un kit ya reconocido, usa el flujo de actualización.

Sigue la [instalación con el artefacto](#artefacto-autónomo-de-entrega).
Fija la versión, guarda el plan, revisa sus destinos y aplica ese plan en
el worktree de adopción. Comprueba `estado --json` y el arranque descrito en
`AGENTS.md`. Guarda las rutas persistentes según el procedimiento Git del
consumidor. Usa el plan para identificar qué guardar y deja el lock y el
diario vivo en el worktree como archivos operativos.

Prepara `gobernanza/config.json` con las rutas y verificadores que correspondan
al proyecto. Consulta el [formato de configuración](FORMATO_NUCLEO.md) y
el mapa de modo ubicable de este manual. El verificador
integrado admite `unittest discover`. Las transiciones de ejecución y
entrega del flujo general requieren informes del kit con casos ejecutados.
Si el proyecto usa otro runner, conserva sus comprobaciones en CI o en
su flujo vigente y enlaza sus salidas reales. Puedes empezar usando el kit
para registrar y consultar contratos mientras ese flujo sigue a cargo de
verificar y cerrar los cambios.

Si el dueño elige activar el hook opcional, su cobertura de edición
directa en Codex se limita al árbol literal `solucion/`. Si el proyecto
decide reorganizar sus rutas, planifica el traslado por separado y verifica
las importaciones, la compilación, CI y las referencias de los contratos.

### 4. Incorporar el historial necesario

| Situación al corte | Cómo tratarla |
|---|---|
| Funcionalidad ya entregada | Cita su commit, tag o entrega y los documentos y resultados disponibles. Si va a cambiar, registra primero su comportamiento vigente y sus criterios comprobables. Identifica la fuente, el SHA y lo que queda por confirmar. |
| Implementación abierta | Conserva la rama y su procedencia. Si pasa al kit, enlaza el estado y la evidencia real alcanzada al borrador de sesión. Revalida el alcance, la base y el acuerdo para el trabajo restante, y prepara las comprobaciones pendientes antes de seguir construyendo. |
| Idea, deuda o incidente pendiente | Mantén el enlace al backlog. Al elegirlo para ejecución, traduce la parte acordada en un contrato o criterio y abre su sesión conforme al flujo vigente. |
| Contratos y sesiones del formato V2 del kit | Selecciona el inventario compatible, prepara el mapa y simula `sdd migrar`. Revisa la procedencia y aplica la migración con el acuerdo que la cubre. Conserva la referencia a los originales en Git. |

Para documentación libre, cita sus fuentes y usa `sdd registrar` para
formalizar lo que el proyecto gobernará. Sigue el [procedimiento del registro
SDD](FORMATO_NUCLEO.md#registro-documental-sdd).

El historial Git es la fuente de lo ya ocurrido. Conserva los tags y el
versionado anterior con su significado original. Una prueba ejecutada ahora
caracteriza la base actual. Las aprobaciones, ejecuciones y aceptaciones
anteriores se consignan sólo cuando existe constancia de ellas.

### 5. Comprobar el primer recorrido

Si el alcance incluye SDD, genera el índice con `sdd indice --escribir`
usando el prefijo de tu modalidad y guarda el resultado en Git. Desde un
clon local del candidato comprueba el arranque del kit, los enlaces de
`AGENTS.md` y, cuando corresponda, `sdd indice --comprobar`, `sdd seccion`
y `sdd traza` para el contrato y la primera sesión registrada.

Repite las comprobaciones habituales y compara con la línea base. Deja en
la guía del consumidor el SHA del corte, la versión instalada, el mapa de
rutas, las ramas que siguen su flujo previo y la próxima sesión que
arrancará con el kit.

### Ejemplo con una rama abierta

Un servicio ya publicado guarda su código en `src/`, sus pruebas en
`tests/` y sus decisiones en `docs/`. Una rama está corrigiendo la
creación de cuentas. El equipo registra el SHA de la rama de integración,
ejecuta su suite y prepara la instalación en otro worktree. Declara `src/`
como solución y empieza por el archivo de pruebas de cuentas una vez
vinculados sus casos a los criterios. Conserva los documentos en `docs/`.

El equipo acuerda que la corrección se verifique y cierre con su flujo vigente y
registra el commit en el que se integra. Ya sobre esa base, vincula la
especificación y las pruebas actuales a la ficha funcional de creación
de cuentas. La siguiente mejora es la primera sesión del kit. La guía
del consumidor apunta al corte, a la corrección integrada y a esa sesión.

## Artefacto autónomo de entrega

Tras extraer el ZIP, conserva juntos el lanzador `instalar.py`, `entrega.json`
y las carpetas de paquete. Selecciona el mismo modo del consumidor durante
una actualización. El modo ubicable requiere que el consumidor declare su
raíz en `gobernanza/rutas-kit.json`.

```sh
python3 -I instalar.py --raiz R planificar --accion instalar --modo aislado --salida PLAN.json
python3 -I instalar.py --raiz R aplicar --plan PLAN.json
python3 -I instalar.py --raiz R estado --json
```

En una instalación existente selecciona `--accion actualizar`. Revisa el plan
antes de aplicar. Para activar el hook de solución para Codex, añade
`--activar-hook-solucion` al plan de la operación. El host necesita cargar
la configuración del hook para aplicar sus reglas.

## Modalidades

- Estándar. Usa un espacio Python conocido dentro del consumidor y la entrada
  `python3 -m gobernanza` desde su raíz Git.
- Aislada. Usa la entrada `python3 -I .gobernanza-kit/gestionar.py operar` y
  mantiene su runtime separado del Python del proyecto.
- Ubicable. Usa un directorio asignado por el consumidor y la entrada
  `python3 -I RUTA/gestionar.py operar`. Declara la ruta en
  `gobernanza/rutas-kit.json` antes de planear.

```json
{"schema":1,"rutas":{"instalacion":"local/kit"}}
```

## Actualización, diario y recuperación

La actualización reemplaza las rutas gestionadas. El plan muestra fuentes,
huellas, modalidad y destinos. La transacción coteja las imágenes anteriores
y nuevas y preserva archivos, contratos, sesiones e instrucciones del consumidor.
Tras completar el cambio queda activo el slot de la nueva versión.

Si se interrumpe una operación, conserva el artefacto que la inició y usa su
lanzador para recuperar. El diario identifica los destinos y las imágenes
necesarias. Consulta el estado después de recuperar.

```sh
python3 -I instalar.py --raiz R recuperar --json
python3 -I instalar.py --raiz R estado --json
```
