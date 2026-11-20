---
name: gobernanza-local
description: Procedimiento operativo de la versión del kit conservada dentro del consumidor; acuerdos, pruebas, guardados y cierre con autonomía dentro del alcance real.
---

# Trabajo con gobernanza local instalada

## Identificar las dos raíces

Este documento vive en `<slot>/contenido/skill/SKILL.md`. El directorio
`contenido/` es `raiz_kit`. Conserva el código, esta skill y sus referencias de
la versión instalada. `raiz_trabajo` es la raíz Git del consumidor. Lee la
entrada a la skill enlazada desde AGENTS para ubicar el selector `activo.json`
y el slot que identifica. En las entregas de ruta fija esa entrada vive
en `gobernanza/kit-local` para los tres modos.

Las referencias del procedimiento viven aquí: [guía](../docs/kit-local/GUIA.md),
[formato del núcleo](../docs/kit-local/FORMATO_NUCLEO.md),
[ejecución](../docs/kit-local/FORMATO_EJECUCION.md),
[entrega](../docs/kit-local/FORMATO_ENTREGA.md) y
[distribución](../docs/kit-local/FORMATO_DISTRIBUCION.md).
El [diseño original](../docs/kit-local/DISENO.md) y el
[piloto](../docs/kit-local/SESION_PILOTO.md) se conservan como antecedentes literales;
sus afirmaciones históricas de comandos aún inexistentes no sustituyen al formato
y ayuda de la versión instalada.

No dependas del checkout autor, sus rutas absolutas, un PYTHONPATH oculto ni una
instalación global mutable. Al mover o clonar el consumidor se conservan estas
referencias locales. Python, Git y POSIX siguen siendo requisitos del entorno.

## Orientarse y acordar

Lee AGENTS.md y aplica su puerta de navegación antes de abrir continuidad,
contratos o planes. Si falta un objetivo, pregunta o hito concreto, pide que
se precise y espera. Hasta entonces limita las lecturas a AGENTS y a la guía
de navegación que corresponda. Con un objetivo, consulta las fuentes y el
módulo que indique la guía. Para intervenir en una sesión, revisa su punto de
continuación, F/revisión, spec y contratos dependientes. Usa `contexto` cuando
aporte razones para ampliar la lectura. La sesión conserva su ID al cambiar
de chat y el chat identifica al actor.

Los borradores permiten analizar y redactar documentos. Para ejecutar conserva la
referencia al pedido real, versión del plan, funcionalidades, objetos, exclusiones
y facultades de integración. Escribir un campo autorizante no crea permiso.
Una autorización existente sigue válida al retomar dentro del mismo alcance.
Cada escritor usa un worktree propio; un plan futuro no modifica el acuerdo activo.

## Registrar y retomar una sesión SDD

Sigue el [formato SDD](../docs/kit-local/FORMATO_NUCLEO.md#registro-documental-sdd)
para contratos y sesiones tipificados. Usa `sdd/indice.md` para localizar
identidades, `sdd seccion` para leer el fragmento citado y `sdd traza` para
retomar una sesión. Añade `--json` a las consultas.

Conserva el plan libre en el texto de la sesión. Prepara el lote con las
referencias exactas, simúlalo con `sdd registrar --entrada LOTE.json --json`
y revisa el resultado antes de aplicar. Comprueba el mandato y la aprobación
aplicables antes de promover a preparación y ejecutar `iniciar`. Usa los
referentes V2 del consumidor mientras su adopción siga pendiente.

Dentro del acuerdo decide detalles compatibles, corrige defectos, verifica y
guarda sin pedir permiso por cada micropaso. Eleva únicamente decisiones materiales
nuevas, aceptación humana prevista o excepciones aplicables. Prepara antes el
resultado concreto que necesite revisión.

## Preparar, construir y verificar

Consulta la ayuda desde la raíz de trabajo. En modo estándar usa
`python3 -m gobernanza --help`. Si el bloque gestionado de AGENTS declara modo
aislado, usa el administrador que indica AGENTS. En la ruta fija ejecuta
`python3 -I gobernanza/kit-local/gestionar.py operar --help` y pasa
`contexto`, `validar`, `iniciar`, `verificar`, `cerrar` y `sdd` desde esa entrada.
En modo ubicable usa el administrador del bloque de AGENTS. Para registro y
consulta tipificada prueba `sdd --help` con el prefijo que corresponda según
la [guía instalada](../docs/kit-local/GUIA.md#elegir-la-entrada-operativa).
Con el administrador, coloca `--raiz` antes de `operar`.

Antes de nueva conducta escribe o identifica sus pruebas y vincula cada caso con
ID, F/revisión/criterio, verificador y selector junto al método. Conserva el rojo
real por conducta pendiente; cero casos, importaciones rotas o errores de entorno
no lo demuestran. Una conservación puede partir de un paquete adecuado en verde,
con su justificación. El scaffold mínimo pertenece a la preparación.

Construye por incrementos dentro del alcance y conserva comandos, contenido,
casos descubiertos/ejecutados/omitidos, resultados, exit y siguiente paso. Las
pruebas heredadas y consumidores afectados siguen vigentes. No retires casos,
aserciones, fixtures o selectores para acomodar un defecto. Una excepción sobre
obligaciones aceptadas exige dictamen concreto de un revisor independiente o del
orquestador que no escribió el cambio; si no existe, decide el dueño.

El inicio guarda una captura anclada en Git; repetirlo no amplía autoridad ni
reinicia una fase avanzada. Verificar ejecuta pruebas reales en una copia y publica
el informe fuera de entradas. Un inventario estático o validación estructural no
acredita pruebas ejecutadas, aceptación humana ni entrega. Distingue los dictámenes
manuales o fallos inyectados de controles reales y procesos realmente terminados.

Si el dueño activó los guardados Codex para este worktree, comprueba la rama
activa y el alcance de los archivos antes de usar `git -C RUTA_ABSOLUTA add --
ARCHIVOS` y `git -C RUTA_ABSOLUTA commit -m MENSAJE`. Revisa también el índice
completo antes del commit. Para integrar el candidato
verificado, comprueba que el acuerdo cubre la integración y registra la
aprobación explícita del dueño. Desde el directorio de `main` usa
`git merge --no-ff RAMA`. Aplica esta comprobación humana también cuando
Codex revise comandos automáticamente.

## Revisar, guardar y cerrar

Prepara casos humanos con versión/commit, arranque, URL o comando, datos, pasos,
criterios y resultados esperados. Solo el dueño comunica su aceptación; no la
deduzcas de capturas, automatización o de tu opinión. Mientras espera, avanza en
trabajo independiente autorizado. Un cambio posterior invalida casos afectados.

Incorpora enmiendas y consolida el cierre, preservando historia del acuerdo y
asignando deuda. Conserva guardados coherentes y estado fallido antes de recuperar
una copia aislada; respaldo de datos persistentes cuando corresponda. Git recupera
lo versionado; no presupongas que respalda otros datos.

Preparar cierre no integra. La confirmación comprueba una integración ya realizada
con base, fuente y árbol verificados. Integración, despliegue y aceptación humana
son obligaciones distintas; siguen el acuerdo aplicable. Evita SHAs autorreferentes.

## Mantener esta instalación

Desde la raíz Git consulta el plan de actualización con
`./gobernanza-kit actualizar --solo-plan`. Ejecuta
`./gobernanza-kit actualizar` cuando el pedido autorice la actualización.
Para elegir la release añade `--version V3.02`. En proyectos anteriores al
lanzador, usa la orden de migración de la guía. La activación de
`--activar-hook-solucion` se solicita expresamente.

La [guía de la versión instalada](../docs/kit-local/GUIA.md#instalar-por-primera-vez)
describe la planificación, aplicación, estado y recuperación con `instalar.py`
del artefacto elegido. Revisa la modalidad y las imágenes del plan. El control
local de solución requiere la opción explícita `--activar-hook-solucion` y
la decisión aplicable del dueño. La actualización usa una versión fija y
preserva configuración, contratos y datos consumidores.

Un slot alterado o una transacción pendiente se diagnostica conservando evidencia.
Desde otra carpeta usa el administrador local y `--raiz` explícita. Si se
interrumpió una instalación antes de publicar el administrador, la entrada
`entradas/gestionar.py` del slot conservado también permite recuperar. La guía
explica los comandos. Reinicia procesos Python al cambiar de versión; no hay
recarga implícita ni garantía de detección desde un módulo antiguo aún cargado.


## Planificar y vincular la ejecución

Cuando el dueño indique un fin de producto, consulta `ruta consultar --json` con
la entrada del proyecto. Para registrar un nuevo resultado usa `ruta plantilla
meta`, o `ruta plantilla objetivo` para desglosar una meta. Completa el objeto
y usa `ruta registrar --entrada OPERACION.json --aplicar --json`. Antes de
ejecutar producto vincula la sesión a una meta u objetivos de la misma meta con
`ruta vincular --sesion FOLIO --destino ID --aplicar`. La preparación puede
comenzar antes de ese vínculo. La guía instalada describe la adopción mediante
`ruta configurar` y cómo comprobar el tramo con `ruta consultar --hasta ID`.
