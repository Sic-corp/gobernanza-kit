# Guía del kit local instalado

<!-- gobernanza-kit:arranque-por-objetivo -->
<!-- gobernanza-kit:sdd-en-agents -->

El consumidor conserva su versión del kit, su código y las referencias en un slot
local. La entrada del bloque de `AGENTS.md` identifica `activo.json` y el slot.
Python 3.10 o posterior, Git y POSIX son requisitos.

Para trabajar sobre una sesión sigue la [skill operativa](../../skill/SKILL.md).
Para preparar el registro consulta el [formato SDD](FORMATO_NUCLEO.md#registro-documental-sdd).
Los formatos de [ejecución](FORMATO_EJECUCION.md), [entrega](FORMATO_ENTREGA.md)
y [distribución](FORMATO_DISTRIBUCION.md) detallan sus comprobaciones. El
[diseño](DISENO.md) y el [piloto](SESION_PILOTO.md) incluyen el contrato y un ejemplo de uso.

## Elegir la entrada operativa

Usa la modalidad indicada en el bloque gestionado de `AGENTS.md` y ejecuta
la ayuda desde la raíz Git del consumidor.

| Modalidad | Ayuda del registro |
|---|---|
| Estándar | `python3 -m gobernanza sdd --help` |
| Aislada | `python3 -I .gobernanza-kit/gestionar.py operar sdd --help` |
| Ubicable | `python3 -I RUTA/gestionar.py operar sdd --help` |

En ubicable sustituye `RUTA` por la raíz de instalación asignada en
`gobernanza/rutas-kit.json`. Desde otra carpeta usa la ruta absoluta al
administrador y pasa `--raiz R` antes de `operar`. Los comandos de trabajo
usan la misma entrada y la distribución dispone de su propio instalador.

## Trabajar con el registro SDD

Usa `sdd/indice.md` para ubicar contratos registrados. `sdd seccion --ref
'SPEC-0001@v1#SEC-ALTA' --json` devuelve el fragmento citado y `sdd traza
--sesion S01-01 --json` devuelve la cadena de una sesión. Usa `--arbol REF`
para una consulta histórica. Comprueba la vigencia con `sdd indice --comprobar`
y vuelve a generarlo con `sdd indice --escribir` cuando sea necesario.

Conserva el Markdown del plan acordado como el campo `texto` de la sesión.
Las ideas aún exploratorias pueden quedar en `playground/`. Para escribir un
borrador oficial, prepara un lote JSON con `base`, `cambios`, campos tipados y
el texto del plan. Con la modalidad estándar, prueba y registra el lote así.

```sh
python3 -m gobernanza sdd registrar --entrada LOTE.json --json
python3 -m gobernanza sdd registrar --entrada LOTE.json --aplicar --json
```

Aplica el lote después de revisar la simulación. Sustituye el prefijo de esos
comandos por el de tu modalidad si usas un administrador. El paso a preparación
requiere un mandato y la aprobación exacta que le corresponde. Consulta los
[pasos y formatos de aprobación](FORMATO_NUCLEO.md#registro-documental-sdd).
Un proyecto con fichas V2 conserva sus contratos. La adopción a SDD se propone
con `sdd migrar` y se autoriza explícitamente.

## AGENTS.md de referencia

El gestor publica su bloque entre los delimitadores del kit. Conserva las
instrucciones del consumidor y los enlaces a su guía canónica. La navegación
instalada vive en `<base>/skills/navegar-gobernanza/SKILL.md`. La base es
`.gobernanza-kit` en estándar y aislado, o la raíz asignada en ubicable.

```markdown
<!-- Aquí va el bloque completo que genera el kit. -->

# Instrucciones del repositorio

## Orientación local

Enlaza la guía canónica propia si existe. Si el pedido identifica un objetivo,
sigue esa guía y consulta las fuentes pertinentes.

## Fuentes del proyecto

En un proyecto con registro SDD, enlaza el índice `sdd/indice.md`.
Identifica la sesión por su folio y usa `sdd traza` para recuperar su estado y
sus fuentes. Declara las continuidades locales que correspondan a cada dominio.

## Autoridad y controles

Indica qué decisiones requieren aprobación, cómo se verifican los cambios
y qué controles y convenciones locales rigen la sesión.
```

Al instalar, el bloque gestionado precede las instrucciones existentes. Al
actualizar, el gestor reconoce la generación del bloque y conserva el texto
ajeno. Si el consumidor declara su propia guía, conserva su enlace y sus
instrucciones. Prueba «Sigamos con este repositorio» en una sesión nueva.
La respuesta esperada pide un objetivo o hito tras leer sólo AGENTS y la guía
canónica.

## Instalar por primera vez


Desde la raíz Git del proyecto, instala la release estable publicada en GitHub.
En Bash o Zsh activa `pipefail` para propagar los errores de descarga.

```sh
set -o pipefail
curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- instalar
```

Para actualizar desde V3.02, ejecuta `./gobernanza-kit actualizar`. Si el
proyecto ya tiene una versión anterior al lanzador, ejecuta la primera
actualización con el bootstrap.

```sh
set -o pipefail
curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- actualizar
```

En otros shells POSIX puedes comprobar que la descarga terminó antes de
iniciar el instalador. Sustituye `instalar` por `actualizar` para migrar.

```sh
kit=$(curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh) && printf '%s\n' "$kit" | sh -s -- instalar
```

Añade `--solo-plan` para revisar los destinos y las versiones que se retirarán,
`--version V3.02` para fijar la release o `--activar-hook-solucion` para
solicitar el control de edición de `solucion/`. La descarga usa el ZIP del tag
elegido y comprueba su SHA-256 antes de ejecutar el instalador. El instalador vuelve a
comprobar las precondiciones del plan al aplicar la transacción.

### Instalación con el artefacto descargado

Usa la carpeta del artefacto que contiene `instalar.py`. Sustituye `R` por la
raíz del consumidor. Selecciona `estandar`, `aislado` o `ubicable` en el plan.
Para ubicable declara antes el mapa de instalación de ese consumidor.

```sh
python3 -I instalar.py --raiz R planificar --accion instalar --modo estandar --salida PLAN-INSTALAR.json
python3 -I instalar.py --raiz R aplicar --plan PLAN-INSTALAR.json
python3 -I instalar.py --raiz R estado --json
```

Revisa los destinos, la modalidad y las identidades antes de aplicar. El
lanzador selecciona el paquete junto al artefacto. El dueño puede incluir
`--activar-hook-solucion` al planificar si autoriza el control de Codex sobre
ediciones directas de `solucion/`. El plan muestra la configuración que va a
publicar. La carga en el host y la aprobación del mandato se comprueban por
separado. Consulta la referencia de autoridad de la guía de navegación para
preparar la rama, el acuerdo y la evidencia de una sesión con el hook.

## Actualizar una instalación existente

Usa el artefacto de la versión elegida y conserva la modalidad que indica el
`AGENTS.md` consumidor. Este ejemplo actualiza una instalación estándar.

```sh
python3 -I instalar.py --raiz R planificar --accion actualizar --modo estandar --salida PLAN-ACTUALIZAR.json
python3 -I instalar.py --raiz R aplicar --plan PLAN-ACTUALIZAR.json
python3 -I instalar.py --raiz R estado --json
```

La actualización sustituye la instalación gestionada. Retira los slots
anteriores íntegros al completar la transacción y usa el diario para recuperar
una interrupción. El plan y el manifiesto identifican la versión, commit y
huellas. Configuración, solución, contratos, sesiones, evidencias e
instrucciones propias pertenecen al consumidor. El guardado de la instalación
en Git sigue su procedimiento. Reinicia procesos Python al cambiar de versión.

## Recuperar una interrupción

Conserva el artefacto que inició el cambio y usa su lanzador para recuperar.
La operación usa el diario y las imágenes conservadas para cotejar el estado.

```sh
python3 -I instalar.py --raiz R recuperar --json
python3 -I instalar.py --raiz R estado --json
```

El [protocolo de distribución](FORMATO_DISTRIBUCION.md#actualización-diario-y-recuperación)
explica la recuperación mediante las entradas locales de instalaciones previas.
