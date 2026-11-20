# Formato y API del núcleo · Esquema 1

`contexto` y `validar` interpretan los contratos de la raíz de trabajo.
La CLI expone ambas operaciones y conserva sus diagnósticos.
Las decisiones de entrega y la evidencia ejecutada tienen su propio
[formato](FORMATO_ENTREGA.md).

`gobernanza/config.json` declara `schema: 1`, proyecto, patrones `documentos`,
raíces `solucion`, `pruebas` y `controles`, verificadores como lista de objetos
con id/runner/cwd/args/salidas_permitidas. El núcleo solo los inspecciona.
Las rutas son relativas a la raíz explícita. Se rechazan escapes por rutas o
enlaces efectivos antes de leer contenido. No se depende del checkout autor.

Los documentos mecánicos llevan JSON entre dos líneas `---`. Specs: id, schema,
version y funcionalidades. F: id, modulo, revision_actual, revisiones (enteros),
criterios (mapa de número de revisión como texto a lista de IDs), objetos (rutas
o patrones), dependencias y sesiones. `evidencias_por_revision` enumera las rutas
de evidencia relativas a la raíz, agrupadas por número de revisión como texto.
La prosa describe cada criterio y el JSON identifica su revisión. Sesiones: id,
funcionalidades y dependencias. Se conserva compatibilidad con las claves del
piloto. Los campos adicionales se conservan sin otorgarles autoridad.
JSON rechaza claves duplicadas, constantes no estándar y booleanos usados como
esquema o revisión. Los campos de relación conservan su tipo: funcionalidades
enlaza F, sesiones enlaza S/G y el propietario compartido es un spec M.

Una referencia propuesta se declara en `funcionalidades_propuestas` o
`dependencias_propuestas`, o como `{"ref":"F-9999@r1","estado":"propuesta"}`.
La ausencia de esa referencia es pendiente explícito. Un estado borrador por sí
solo no convierte toda referencia rota en admisible. Las referencias externas
requieren proyecto y evidencia en `referencias_externas` de configuración. No se
resuelven a contratos locales ni se leen otros repositorios.
Esto incluye revisiones futuras propuestas de una identidad que ya tiene otra
revisión local. Una referencia malformada no se admite como pendiente.

Objetos propios: `objetos` de F. Objetos compartidos: `objetos_compartidos` del
spec, con `ruta` y `consumidores`. El módulo es propietario único. El contexto
recorre dependencias y consumidores, usa visitados y explica inclusiones. No
expande toda F de un módulo por el mero hecho de compartir el módulo.

Pruebas: comentario JSON `# gobernanza-test: {...}` inmediatamente antes del
método `test_*` o de su primer decorador, con la misma indentación. Campos:
id, criterio `F-####@rN/CNN`, verificador y selector relativo a la raíz de pruebas
(`test_contexto.ContextoTests.test_por_sesion`, por ejemplo). Se usa AST y tokens.
Una cadena de texto con ese prefijo no es un vínculo. Solo se inspeccionan métodos
de clases declaradas de unittest. No se importan ni ejecutan módulos. Este inventario
estático no promete descubrimiento dinámico, herencia o equivalencia de tests.
Se reconocen `unittest.TestCase`, `TestCase`, sus alias de importación y herencia
local declarada en orden. No se resuelve herencia entre módulos, factories,
`load_tests`, asignaciones dinámicas o parametrizadores. Los directorios enlazados
no se recorren: se informa diagnóstico y se pide declarar la ruta interna real.
Los archivos alcanzados desde raíces solapadas se inventarían una sola vez.

Resultados: diccionario con operacion, estado (`valido`/`invalido`), codigo
(0 estructura/consulta satisfecha, 1 condición incumplida, 2 uso inválido), resumen,
errores, pendientes, contratos, criterios y pruebas_declaradas. Cada diagnóstico
identifica codigo/ruta/requisito/mensaje/resolucion. Contratos contienen id,
referencia, tipo, ruta, estado y razones de inclusión. Las pruebas declaradas
incluyen procedencia/línea y `descubierto: false`.

`limites` declara siempre autoridad, pruebas_ejecutadas, descubrimiento_runner
y entrega_aceptada como false. Un verde de las pruebas del propio kit sí es una
ejecución real externa a esta API. Validar un consumidor nunca la inventa.

## Contexto integrado

`contexto(raiz, *, sesion=None, funcionalidad=None, ruta=None,
arbol="worktree", historico=False, integrada=False, version=None)` consulta la raíz indicada.
`arbol` selecciona `worktree`, `staged` o una ref de Git. Con el versionado de
solución activo, `integrada=True` y un folio F consultan su revisión integrada
vigente. `version="V1.01"` consulta el árbol de esa entrega. Se puede filtrar
por una F o ruta. La CLI ofrece `--integrada` y `--version V1.01`.

En esas consultas, el recibo identifica el commit y las entregas registradas.
Cada traza funcional identifica la F, el spec dueño, objetos propios y
compartidos, pruebas directas y heredadas, y evidencia declarada por revisión.
La evidencia de entrega se consulta por el recibo y sus fuentes.
Una consulta histórica toma fichas y pruebas de su propio árbol, incluso si el
checkout contiene una revisión posterior. [Formato de entrega](FORMATO_ENTREGA.md#registro-de-versiones).

## Perfil optativo de Heimdall

El consumidor selecciona `"perfil_operacion": "heimdall-v2"` en
`gobernanza/config.json` de esquema 1, con proyecto `heimdall`.
Guardar esa selección antes del primer uso bajo su propio acuerdo.
Las operaciones vigentes cotejan el perfil guardado, el índice y el
worktree. Una consulta histórica usa una ref y el selector
`historico` de la API, o `contexto --arbol REF` de la CLI.
El despacho de los consumidores con config original conserva el
contrato anterior.

Para un folio, lee su plan canónico, módulo, estado, evidencia y contratos.
G usa `gobernanza/sesiones/` y `gobernanza/sdd/`. S usa
`sesiones/` y `sdd/`. Las fichas S se consultan con revisión explícita.
Una proyección del puente G→S conserva ruta, ref, blob y huella.
Su vigencia se comprueba con la rama fuente. La respuesta identifica
perfil, procedencia, plan y continuidad, junto con los límites
de una consulta estructural. Una contradicción produce diagnóstico
de las fuentes implicadas.

## Registro documental SDD

Elige el comando de tu modalidad en la guía instalada.
Los ejemplos siguientes muestran el prefijo estándar. Desde un administrador
mantén `operar` antes del comando de trabajo.

`python3 -m gobernanza sdd registrar --entrada lote.json --json` simula una
operación contra el commit completo indicado en `base`. Con `--aplicar` guarda
el lote y su constancia. Cada elemento de `cambios` declara `accion`, los
`datos` de la cabecera JSON de esquema 3 y el `texto` Markdown libre.
Las ideas exploratorias pueden quedar en `playground/`. Al abrir una sesión
conserva íntegro el texto del plan. Este ejemplo supone que `F-0001@r1` existe
y que el plan está en `playground/plan.md`.

```python
import json
from pathlib import Path
import subprocess

base = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
texto = Path("playground/plan.md").read_bytes().decode("utf-8")
datos = {"schema": 3, "tipo": "sesion", "ref": "S01-01", "estado": "borrador",
         "funcionalidades": ["F-0001@r1"], "plan": 1}
lote = {"base": base, "cambios": [{"accion": "alta", "datos": datos, "texto": texto}]}
Path("lote.json").write_text(json.dumps(lote, ensure_ascii=False), encoding="utf-8")
```

Para activar el plan, agrega `mandato` mediante `modificar`. El mandato
contiene `referencia_pedido`, las mismas `funcionalidades` de la sesión,
`scaffold` como lista expresa de archivos y `alcance` con los grupos
`producto`, `pruebas`, `documentos` y `controles`. Declara los casos humanos
acordados y el permiso de integración cuando apliquen. Las transiciones que
autoriza ese mandato se declaran en `registro_sdd`. El campo `plan` conserva
la versión del plan en la sesión. Si el consumidor activó el hook de
solución para sesiones SDD, `mandato.rama` identifica la ref Git completa.
Por ejemplo, `refs/heads/codex/S01-01/ejemplo`. Inclúyela antes de aprobar
el borrador. Una sesión patrocinadora vigente puede autorizar la transición a preparación
mediante su acuerdo. Si se inicia desde cero, el revisor guarda en Git
`sdd/aprobaciones/S01-01.json` con `schema: 3`, `sesion: "S01-01"`, `sha256`
del Markdown completo en estado borrador y `referencia_dueno` con la decisión
real. Usa `git show HEAD:sdd/registro/S01-01.md | shasum -a 256` para obtener
la huella de esa versión. En el lote que sólo promueve ese borrador a
`preparacion`, `aprobacion` lleva la `ruta` del JSON y su `commit` completo.
Toma `base` del `HEAD` vigente al armar el lote. Tras registrar la transición,
`iniciar --sesion S01-01` captura el acuerdo de la sesión.

Las secciones tienen anclas explícitas como
`<!-- gobernanza:seccion SEC-ALTA -->`. Consulta con
`sdd seccion --ref 'SPEC-0001@v1#SEC-ALTA' --json`. La F conserva su folio
y cada revisión declara módulo, criterios y citas. Una corrección dentro
del contrato conserva la revisión. Una evolución registra la siguiente.

`sdd traza --sesion S01-01 --json` sigue el plan, contratos y evidencia.
`sdd indice --escribir --json` regenera el índice y `--comprobar` coteja su
vigencia. El catálogo se consulta en `sdd/indice.md`. Usa `--arbol REF` para
secciones, trazas o índices históricos. Los diagnósticos señalan la referencia
concreta que debe conciliarse.

Para adoptar un corpus V2, prepara el mapa de secciones y simula
`sdd migrar --base COMMIT --asignaciones mapa.json --sesion S01-01 --json`.
Revisa las asociaciones y aplica la operación con el acuerdo correspondiente.
Las consultas históricas por V usan el árbol de su entrega.
