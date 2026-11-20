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

En estándar, `python3 -m gobernanza sdd --help` abre la ayuda SDD.
En aislado y ubicable, usa `python3 -I gobernanza/kit-local/gestionar.py operar --help`
y pasa `sdd` como verbo. Desde otra carpeta usa la ruta absoluta al
administrador y pasa `--raiz R` antes de `operar`.

Si consultas una instalación histórica, conserva la ruta indicada en su
bloque de AGENTS. Sus entradas eran
`python3 -I .gobernanza-kit/gestionar.py operar sdd --help` en aislado y
`python3 -I RUTA/gestionar.py operar sdd --help` en ubicable. En ese caso,
`RUTA` representa el directorio de la instalación previa.

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

## Trabajar con la ruta de desarrollo

Usa el prefijo de la modalidad instalada. Desde la raíz del candidato, ejecuta
`ruta configurar --aplicar` para adoptar el vínculo de ejecución. Conserva las
ubicaciones de solución y pruebas que ya estén declaradas. Si faltan, recógelas
del dueño. En Terminal se preguntan al aplicar. En un agente usa `--solucion src/`
y `--pruebas tests/`, repetibles. La operación guarda únicamente la configuración
en el repositorio elegido. La hoja nace con la primera meta.

| Intención | Operación después del prefijo |
| --- | --- |
| Plantilla de meta o de objetivo | `ruta plantilla meta --json` o `ruta plantilla objetivo --json` |
| Guardar una operación del agente | `ruta registrar --entrada operacion.json --aplicar --json` |
| Consultar el siguiente hito | `ruta consultar --json` |
| Encargar el tramo hasta un destino | `ruta consultar --hasta OBJ-02 --json` |
| Vincular una sesión a una meta | `ruta vincular --sesion S01-01 --destino META-01 --aplicar --json` |
| Vincular a varios objetivos hermanos | `ruta vincular --sesion S01-01 --destino OBJ-01 --destino OBJ-02 --aplicar --json` |
| Abrir el tablero del proyecto | `tablero` |

Copia el objeto `plantilla` al archivo de la operación y escribe el resultado
en `titulo`. Un objetivo requiere la `meta` a la que pertenece. El agente recibe
un `id` al guardar. Opcionalmente fija `posicion` a partir de 1. `actualizar`
admite el ID y los campos modificados. `mover` recibe el ID y su nueva posición.
Completar un hito requiere su criterio y evidencia. Consulta la ruta de nuevo tras
un conflicto. Para simular, omite `--aplicar`. Para reintentar un alta usa la misma
operación con su `base` Git original.

La hoja `sdd/ruta-de-desarrollo.md` y las sesiones de `sdd/registro/` pertenecen al
candidato. El tablero lee el último commit de su rama. Una sesión de producto puede
preparar y verificar sus pruebas antes del vínculo. Al pasar a ejecución o reanudarla
se comprueban el destino y la preparación. Conservar el criterio y la evidencia
permite distinguir una sesión terminada de un resultado alcanzado.

## SDD protegido en Heimdall

El perfil `heimdall-v2` protegido mantiene las lecturas directas de `sdd/`
y `gobernanza/sdd/`. El agente solicita por la API cualquier alta o edición,
incluidos los borradores. El escritor local valida y publica el lote como otra
identidad. El agente conserva sus permisos en la solución y su flujo Git de
trabajo.

### Preparar la copia en macOS

1. El dueño prepara una cuenta estándar de agente y dos clones locales desde
   el mismo commit con `git clone --no-local`. La copia de trabajo pertenece al
   agente salvo el directorio raíz, `gobernanza/` y las dos raíces SDD. La copia de
   autoridad queda dentro de un directorio modo `0700` del escritor. Usa una ruta
   absoluta física en un volumen local con propiedad de archivos activa.
2. Asigna al escritor la propiedad de la raíz de trabajo y de `gobernanza/`.
   Ambos directorios pueden dar escritura al grupo de trabajo con modo `1775`.
   El bit sticky protege las entradas propiedad del escritor. Asigna también al
   escritor la propiedad recursiva de `sdd/` y `gobernanza/sdd/`. En estas raíces
   usa modo `0755` para directorios y permisos de lectura para el agente en los
   archivos, conservando los bits de ejecución versionados. Retira ACL
   extendidas de las rutas de la copia protegida y sus almacenes.
3. Usa un Python compatible y un Git instalados fuera del alcance de escritura
   del agente. Para que Git reconozca la raíz compartida, un lanzador de confianza
   puede ejecutar el binario real con `-c safe.directory=/ruta/fisica/copia`.
   Colócalo como `git` en el `PATH` del agente. La excepción debe ser exacta para
   esa copia.
4. Instala el código del escritor bajo su propia identidad fuera de la copia del
   agente. Usa un directorio de estado vacío modo `0700` y otro directorio para
   el socket modo `0750`, ambos del escritor. El segundo usa el grupo de acceso
   del agente. El servicio comprueba el UID del proceso que se conecta.
5. Guarda la configuración en un archivo modo `0600` del escritor. En
   `referencia` usa la copia de autoridad o una imagen privada preparada por el
   dueño con los estados de módulo usados por el índice. En
   `repositorio_git` usa la copia de autoridad, con su propio directorio
   `.git`. Configura el alcance documental del trabajo autorizado.

```json
{
  "raiz": "/ruta/fisica/copia",
  "estado": "/ruta/privada/estado",
  "socket": "/ruta/socket/sdd.sock",
  "uid_agente": 550,
  "gid_agente": 20,
  "base": "SHA completo del commit compartido",
  "alcance": ["sdd/funcionalidades/", "sdd/INDICE.md"],
  "referencia": "/ruta/privada/autoridad",
  "repositorio_git": "/ruta/privada/autoridad"
}
```

Inicia `python3 -I RUTA/gestionar.py operar sdd servir --config CONFIG.json`
desde la instalación controlada por el escritor. El ejemplo estándar equivalente
es `python3 -m gobernanza sdd servir --config CONFIG.json`. Prueba desde la cuenta
del agente que puede leer ambas raíces y editar la solución. Intenta además
crear, editar, borrar y reemplazar destinos en ambas raíces. Activa la operación
del agente solo tras observar el rechazo del sistema operativo y una llamada
válida a la API.

### Operar con la API

```sh
export GOBERNANZA_SDD_SOCKET=/ruta/socket/sdd.sock
python3 -I gobernanza/kit-local/gestionar.py operar sdd estado --json
python3 -I gobernanza/kit-local/gestionar.py operar sdd registrar --entrada LOTE.json --json
python3 -I gobernanza/kit-local/gestionar.py operar sdd registrar --entrada LOTE.json --aplicar --json
python3 -I gobernanza/kit-local/gestionar.py operar sdd indice --escribir --json
```

El lote contiene `base`, `generacion` de la consulta de estado y una lista
`cambios`. Cada cambio indica `accion` (`alta` o `modificar`), `ruta`,
`tipo` y `texto`. Usa `spec` o `enmienda` para sus contratos nativos y
`auxiliar` para insumos, propuestas y referencias textuales. Las fichas usan
`tipo: "ficha"` y un objeto `datos` independiente de la prosa.

```json
{
  "accion": "alta",
  "tipo": "ficha",
  "ruta": "sdd/funcionalidades/F-9001_lectura.md",
  "datos": {
    "id": "F-9001",
    "modulo": "heimdall",
    "estado": "Borrador",
    "rutas": ["solucion/heimdall/"],
    "dependencias": [],
    "componentes": ["sdd/spec_heimdall.md"],
    "revisiones": [{"revision": 1, "criterios": {"C01": "La consulta devuelve el documento vigente."}}]
  },
  "texto": "# F-9001 — Lectura\n\nContrato de la consulta.\n"
}
```

Un cambio `{"accion":"indice"}` solicita regenerar el índice en el mismo lote.
Las operaciones que requieren decisión del dueño se aplican por la misma API
desde la identidad del escritor. Guarda en Git desde la cuenta del agente
después de aplicar el lote. Si falla la conexión, consulta el estado o reintenta
el lote idéntico. El recibo permite reconocer una aplicación completada.

### Aceptar un candidato y recuperar

Genera un bundle del commit candidato bajo la identidad del agente e impórtalo
en la copia privada de autoridad. Como escritor, ejecuta `sdd aceptar-candidato --config CONFIG.json --candidato SHA`.
El comando comprueba el índice y el contenido SDD contra la generación vigente
mientras conserva el bloqueo de lotes. Un resultado válido avanza la referencia
local `refs/heads/sdd-aceptada`. La integración acordada usa ese SHA. Si cambian
las fuentes del índice en los estados de módulo, prepara la nueva imagen privada
de referencia y vuelve a generar el índice mediante la API antes de aceptar.

Conserva un clon o commit de la base, la configuración privada y el directorio
de estado del escritor. Si se interrumpe una publicación, reinicia el servicio
con la misma configuración. La consulta de estado recupera el lote pendiente y
coteja la imagen antes de habilitar otra mutación. Para retirar la prueba, detén
el servicio y conserva su evidencia. El siguiente ensayo comienza en una copia
nueva del último SHA aceptado con un directorio de estado nuevo.

## AGENTS.md de referencia

El gestor publica su bloque entre los delimitadores del kit. Conserva las
instrucciones del consumidor y los enlaces a su guía canónica. La navegación
instalada vive en `gobernanza/kit-local/skills/navegar-gobernanza/SKILL.md`.

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
La instalación se fija en `gobernanza/kit-local` desde esa raíz.

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
