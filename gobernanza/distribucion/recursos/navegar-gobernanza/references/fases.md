# Fichas de fase

Elige por objetivo y evidencia. Cada ficha remite a la fuente que gobierna su decisión en el consumidor. Lee dependencias sólo si afectan el caso. Usa visitados y admite ciclos. Ante referencias rotas o propiedad ambigua aplica el contrato de contexto y detén lo dependiente.

## Consulta

- **Entrada** — pregunta concreta de sólo lectura.
- **Lecturas** — fuente o sección exacta pertinente y, si procede, arranque de `AGENTS.md` y contrato de contexto.
- **Condición** — abre otra ficha sólo si la respuesta requiere una decisión o acción de esa fase.
- **Autoridad** — alcance de sólo lectura.
- **Salida** — respuesta sustentada en la fuente y su límite.
- **Recuperación** — si falta evidencia, identifica lo que falta.

## Registro SDD

Aplica esta ficha cuando el proyecto use el registro tipificado. Resuelve la
modalidad con el `AGENTS.md` del consumidor y la guía del slot activo.

- **Consulta** — ubica el contrato en `sdd/indice.md`, o compruébalo con
  `sdd indice --comprobar`. Usa `sdd seccion --ref CITA --json` para una
  versión y sección explícitas.
- **Planificación** — el plan conserva su Markdown en `texto`. Prepara su
  lote con la base Git y las revisiones exactas. Simula con
  `sdd registrar --entrada LOTE.json --json` y usa `--aplicar` al guardar el
  borrador. Las ideas por explorar pueden quedar en `playground/`.
- **Activación** — coteja el mandato y la aprobación aplicable. Registra la
  transición a preparación y captura el acuerdo con `iniciar`. Los informes
  vinculados respaldan las transiciones siguientes. Si el consumidor activa
  el [hook de solución](autoridad-verificacion.md#hook-de-solución-de-codex),
  identifica la rama exacta en el mandato antes de aprobar el plan.
- **Retoma** — usa `sdd traza --sesion FOLIO --json` para recuperar el plan,
  contratos, aprobaciones, cambios y evidencia. Usa `--arbol REF` cuando la
  decisión corresponde a una versión histórica. Para revisar el esquema y los
  ejemplos, abre la sección de registro SDD del formato del núcleo en el slot.

## Insumo y selección de módulo

- **Entrada** — objetivo concreto sin módulo, contrato o alcance identificado.
- **Lecturas** — `AGENTS.md`, contrato de contexto y continuidad pertinente al identificar la raíz y el dominio. Estado si se identifica módulo.
- **Condición** — lee insumo y evidencia enlazados cuando resuelvan la selección.
- **Autoridad** — identifica módulo y contrato con sus fuentes. Escritura requiere autoridad aplicable.
- **Salida** — objetivo, dominio, módulo y siguiente decisión identificados, o falta concreta.
- **Recuperación** — aclara la ambigüedad con evidencia o dueño. Registra la contradicción en el artefacto dueño según el contrato.

## Contratación

- **Entrada** — falta contrato aplicable o una regla contractual debe cambiar.
- **Lecturas** — contrato, cabecera y enmiendas pertinentes. Sigue el procedimiento local de incorporación e índice cuando aplique. Para validar, contrato completo.
- **Condición** — consulta dependencias y criterios de aceptación afectados.
- **Autoridad** — la decisión explícita cubre el texto y versión identificados. Comprueba aparte la autoridad del plan.
- **Salida** — texto revisable o contrato validado con evidencia de decisión. Incorpora número, cuerpo y cabecera juntos cuando corresponda.
- **Recuperación** — resuelve contradicciones y referencias antes de declarar validación.

## Planificación

- **Entrada** — objetivo y módulo identificados. Falta plan que autorice el cambio.
- **Lecturas** — estado del módulo, contratos aplicables, reglas de planificación y ramas. Consulta la plantilla propia si el consumidor la usa. En SDD sigue la [ficha de registro](#registro-sdd).
- **Condición** — consulta impacto, fichas y dependencias aplicables. Para módulo nuevo sigue su procedimiento de arranque. Lee las reglas de contexto ante concurrencia.
- **Autoridad** — prepara un borrador con proyecto, versión, módulo, contratos, alcance y verificación en la rama que establezca el contrato.
- **Salida** — plan completo y revisable. Declara impacto y regresión según el contrato.
- **Recuperación** — si falta contrato validado o el alcance es ambiguo, resuelve esa puerta antes de activar.

## Reanudación

- **Entrada** — hito identificable de trabajo ya iniciado.
- **Lecturas** — estado del módulo, cabecera y apartado pertinente del plan. Arranque de `AGENTS.md` y contrato de contexto.
- **Condición** — abre evidencia enlazada, aprobaciones y contratos sólo cuando la puerta o discrepancia lo requiera. Consulta [trabajo en otro worktree](autoridad-verificacion.md#trabajo-en-otro-worktree) para relevo.
- **Autoridad** — conserva aprobación vigente que cubra exactamente contenido, versión y alcance.
- **Salida** — puerta actual y siguiente acción identificadas sin repetir fases satisfechas.
- **Recuperación** — si las fuentes discrepan, registra la contradicción según el contrato y resuelve antes del efecto dependiente.

## Activación

- **Entrada** — plan en borrador completo para revisión o activación.
- **Lecturas** — plan, evidencia de aprobación, contrato vigente y reglas locales de activación y ramas. Planes activos y Git en la raíz pertinente.
- **Condición** — antes de escribir aplica [preflight](autoridad-verificacion.md#kit-y-preflight). Si el consumidor limita planes activos, comprueba el límite en el dominio aplicable.
- **Autoridad** — verifica aprobación explícita vigente del texto completo y alcance exacto. Registra la autorización en el campo y forma exigidos. Comprueba aparte la autoridad de integración.
- **Salida** — plan activado y rama de ejecución permitida conforme al contrato.
- **Recuperación** — si falta aprobación, presenta el plan completo para decisión. Si faltan contrato, alcance preciso o una condición de activación, detén el efecto. Ante conflicto de planes activos, conserva los planes y remite la decisión al dueño.

## Ejecución y mantenimiento

- **Entrada** — acción concreta dentro de un plan activo aplicable.
- **Lecturas** — cabecera y apartado de alcance del plan, secciones citadas, estado y evidencia de continuación. Contratos locales de ejecución, contexto y concurrencia.
- **Condición** — antes de escribir usa [kit y preflight](autoridad-verificacion.md#kit-y-preflight). Consulta fichas y revisiones afectadas. Comprueba [Git y hooks](autoridad-verificacion.md#git-y-diagnóstico) al iniciar sesión escribiente cuando corresponda.
- **Autoridad** — aprobación, alcance exacto y reglas locales de planes activos. Cada escritor usa worktree propio y alcances solapados se serializan.
- **Salida** — cambio, evidencia y estado atribuibles al módulo dueño.
- **Recuperación** — detén el efecto si faltan alcance o acuerdo, o hay un reclamo incompatible o no resuelto. Prepara decisión para trabajo adicional.

## Verificación

- **Entrada** — criterio de aceptación o comportamiento por comprobar.
- **Lecturas** — criterio del plan y contrato, reglas de pruebas, evidencia y guardado.
- **Condición** — conducta nueva requiere rojo previo y verde posterior. Al cambiar hooks o adaptadores comprueba configuración y efecto real. Sigue [kit](autoridad-verificacion.md#kit-y-preflight) cuando corresponda.
- **Autoridad** — acredita pruebas con resultados de ejecución. El inventario y la validación estructural documentan las comprobaciones que realizaron. Registra aceptación humana sólo mediante la decisión de quien deba emitirla.
- **Salida** — entrada o comando, criterio, resultado observado, estado y evidencia en el módulo dueño.
- **Recuperación** — conserva fallo y contexto. Corrige sólo dentro de alcance y deja pendiente el criterio sin confirmar.

## Integración

- **Entrada** — paquete concreto preparado y revisado con evidencia.
- **Lecturas** — contrato de integración y ramas, permiso, fuente y base actuales, diff, SHAs, pruebas y rutas de cierre. [Decisiones](autoridad-verificacion.md#separación-de-decisiones).
- **Condición** — consulta procedimiento de reversión o integración póstuma sólo si aplica. Antes del efecto comprueba preflight, hooks aplicables y coincidencia del paquete.
- **Autoridad** — autorización explícita que cubra paquete y SHAs exactos. Comprueba si el contrato requiere decisión separada.
- **Salida** — merge y padres/diff comprobados. Suite sobre la base integrada y cierre según las reglas de la transacción.
- **Recuperación** — si cambian refs, diff o SHAs, o falla suite, detén y sigue la transacción contractual. Conserva evidencia, rama y worktree.

## Cierre

- **Entrada** — integración y criterios verificables, o preparación de cierre solicitada.
- **Lecturas** — plan, evidencia del módulo, estado, permiso y contrato local de cierre.
- **Condición** — tras merge ejecuta la suite aplicable en la base integrada si lo exige el contrato. Consulta las rutas y el estado de transacción antes del commit de cierre.
- **Autoridad** — un permiso vivo con suite verde sólo permite lo previsto por ese permiso. Comprueba aparte el commit de cierre y el estado terminal.
- **Salida** — commit de cierre, plan, estado, evidencia y permiso coherentes y observados cuando correspondan. Si falta una condición, cierre pendiente.
- **Recuperación** — conserva error y estado exactos. Ante suite fallida, sigue [recuperación](#recuperación) y la transacción contractual. Respeta el alcance de cierre.

## Recuperación

- **Entrada** — rechazo, contradicción, conflicto, fallo o evidencia incompleta.
- **Lecturas** — mensaje literal, operación, destino, rama, worktree, plan y permiso. [Diagnóstico](autoridad-verificacion.md#git-y-diagnóstico) y contratos correspondientes de contexto y ejecución.
- **Condición** — si hay transacción consulta el procedimiento local de reversión. Si cambia conducta conserva rojo y verde.
- **Autoridad** — conserva los controles aplicables y usa la vía autorizada para cualquier efecto.
- **Salida** — causa reproducible o incertidumbre, evidencia y siguiente paso autorizado.
- **Recuperación** — si no hay vía autorizada, detén lo dependiente y presenta el bloqueo concreto al dueño.

## Entrega

Para actualizar el kit instalado sigue la sección «Actualizar una instalación
existente» de la guía del slot. En la raíz del proyecto,
`./gobernanza-kit actualizar --solo-plan` muestra el cambio previsto.

- **Entrada** — solicitud de registrar o preparar composición de una versión.
- **Lecturas** — contrato funcional y de entrega, manifiesto y fichas aplicables.
- **Condición** — consulta criterios de composición cuando afecten la versión.
- **Autoridad** — decisión y alcance aplicables. Integración y despliegue se acreditan con su propia evidencia.
- **Salida** — composición declarada y verificable.
- **Recuperación** — resuelve discrepancias con evidencia.

## Despliegue

- **Entrada** — solicitud expresa de desplegar o verificar un entorno.
- **Lecturas** — contrato funcional, decisión o plan de despliegue y evidencia del entorno.
- **Condición** — consulta procedimiento de plataforma sólo cuando esté autorizado.
- **Autoridad** — exige la decisión específica de despliegue y la evidencia del entorno para acreditar su resultado.
- **Salida** — evidencia observada del entorno o despliegue pendiente.
- **Recuperación** — identifica autorización o prueba faltante.
