# Autoridad, recuperación y verificación

Esta referencia orienta decisiones concretas. Prevalecen los contratos, el plan y la evidencia vigente. Consulta sólo la sección pertinente en los contratos y enmiendas declarados por el consumidor. Usa `sdd seccion` para referencias SDD y aplica el lector de la guía canónica en los perfiles que lo indiquen.

## Separación de decisiones

La validación contractual cubre el texto y versión aprobados. La aprobación del plan y su activación autorizan sólo el alcance declarado. Registra la evidencia de la decisión según el contrato local, con cita literal si la exige. Aplica las reglas locales de planes activos, dominios y alcance. Si se excede el límite de planes activos, detén la activación o efecto afectado y lleva el conflicto al dueño. Comprueba la autorización exigida para integrar el paquete exacto, incluida la aprobación separada si corresponde. Entrega, aceptación humana y despliegue tienen decisiones y evidencias propias.

Reutiliza una aprobación que siga cubriendo exactamente artefacto, contenido, versión y alcance. La autorización procede de una decisión registrada. Una consulta o un campo autorizante por sí solos carecen de ese efecto.

## Kit y preflight

Antes de escribir, aplica el preflight y los controles que requieran el acuerdo y la superficie de trabajo. Comprueba acuerdo y versión, raíz, rama, escritor efectivo, alcance y reclamos aplicables. Antes de guardar o cerrar revisa además aprobaciones y verificación. Una discrepancia detiene el efecto y se registra en evidencia. Distingue el procedimiento manual de las barreras cuyo efecto se haya observado.

Sigue la skill operativa enlazada en el bloque gestionado de `AGENTS.md`. Ubica el selector, el slot activo y la guía de esa versión a partir de esa entrada. Desde `raiz_trabajo`, usa la modalidad y ayuda de ese kit. Para `contexto` elige un solo selector, como `--sesion <folio>`, `--funcionalidad` o `--ruta` cuando aporten. Si basta la fuente directa, consúltala sin buscar por ruta. Para estado o recuperación de distribución usa la entrada local de administración. Si hay una transacción pendiente, sigue su procedimiento de recuperación antes de operar. `contexto` orienta lecturas. Antes de guardar o cerrar sigue la guía local y revisa aprobaciones y resultados. La ayuda de `cerrar` distingue preparar el cierre de confirmar un merge ya realizado. El procedimiento nativo y la autorización de integración siguen rigiendo sus operaciones.

Para registrar una sesión SDD, la simulación de `sdd registrar` comprueba el
lote con la base Git. Revisa el diagnóstico y las relaciones antes de usar
`--aplicar`. La transición exige su aprobación guardada y el alcance que le
corresponde. `sdd traza --sesion FOLIO --json` permite retomar ese vínculo.
Consulta las [acciones SDD](fases.md#registro-sdd) y el formato del slot activo
según la modalidad del consumidor.

## Trabajo en otro worktree

Consulta `git worktree list --porcelain` y las reglas locales de contexto, ramas y reclamos. Evalúa planes, capas y reclamos en el worktree registrado que contiene el destino. Usa su directorio efectivo. Cada escritor concurrente tiene worktree exclusivo y los alcances solapados se serializan. Para crear o relevar ramas sigue las formas y destinos declarados por el consumidor, conservando identidad y evidencia. Un cambio de chat conserva el plan activo y las aprobaciones que sigan cubriendo el texto exacto.

## Git y diagnóstico

Si el repositorio usa hooks, comprueba la configuración y ejecución que exige su contrato al iniciar una sesión escribiente. Para cambios de hook o adaptador demuestra configuración y ejecución reales, reproducción roja previa y verde posterior. Declara operativa una barrera tras observar su efecto.

Ante rechazo conserva comando, salida literal, destino, worktree, rama, plan, permiso y estado del índice pertinentes. En pre-commit o pre-merge inspecciona `git diff --cached --name-status`, alcance, transiciones y citas. En integración comprueba además permiso y SHAs. Ante conflicto de reclamos consulta las raíces y planes implicados según el contrato de contexto. Si falla la comprobación inicial del hook, limita el trabajo a los borradores que permita el contrato hasta resolver el bloqueo. Diagnostica adaptador y entorno antes de reintentar con el hook habilitado. Si el consumidor distingue superficies con y sin guard, aplica el contrato y los mensajes de la superficie efectiva. Ante un diagnóstico sobre mezcla de raíces, revisa el directorio efectivo y las redirecciones de cada segmento. Si el contrato prevé registro de intervención, localízalo en el worktree evaluado.

Conserva registros, evidencia y controles Git. Trabaja mediante las interfaces de Git y respeta las vías autorizadas para modificar su estado. Ante rechazo, conflicto, árbol sucio o suite fallida, conserva rama y worktree. Sigue el contrato de ramas para transacción, reversión y limpieza. Si la transacción distingue suite verde y commit de cierre, comprueba ambos antes de declarar terminación. Para afirmar despliegue, consulta evidencia del entorno.

### Hook de solución de Codex

La opción `--activar-hook-solucion` publica la configuración de `PreToolUse`
en `.codex/hooks.json` para escrituras directas identificables en `solucion/`.
Comprueba qué configuración cargó el host y su autorización de carga. La
carga del hook y el permiso de la sesión para editar son decisiones distintas.
Si cambian `AGENTS.md`, una skill o la configuración del hook durante una
sesión, identifica las directivas leídas por el agente y la configuración
cargada por el host. Aplica el procedimiento de carga del host cuando
corresponda. El mandato vigente conserva el alcance aprobado hasta tramitar
una revisión. Conserva la evidencia de una invocación observada.

Para una sesión SDD, declara en el borrador aprobado la ref Git completa
en `mandato.rama`, por ejemplo `refs/heads/codex/S01-01/ejemplo`. Trabaja
en el worktree de esa rama y con el acuerdo capturado por `iniciar`. La
preparación permite las pruebas y los archivos de scaffold del alcance.
Antes de editar producto, guarda el informe real de preparación en Git,
vincúlalo en `evidencias` mediante `sdd registrar` y registra el paso a
`ejecucion`. El hook coteja el alcance y la vigencia de ese informe. Una
modificación de la autoridad del plan sigue su revisión y registro aplicables.

En el perfil nativo usa el procedimiento de preflight del consumidor,
su acuerdo activo y el actor, transacción y reclamo (`claim`) que correspondan.
Comprueba la preparación pertinente antes de aplicar cambios de producto.
El hook cubre las llamadas y destinos directos que reconoce. Los controles de
Git, alcance, pruebas e integración conservan sus propias comprobaciones.

## Relevo verificable de ficha

Si se pretende usar una excepción de relevo, consulta la decisión y el procedimiento específico del consumidor. Comprueba sus condiciones de identidad, permiso, aprobaciones, manifiesto, revisión del motor y aceptación cuando sean aplicables. Un recibo cubre sólo las operaciones exactas que declara. Comprueba aparte la autoridad de integración. Si falta una condición, conserva el rechazo.
