# Formato de ejecución

La API del núcleo usa Python 3.10 o posterior y Git. La CLI expone las
operaciones para cada modalidad del kit.

## Árboles

`materializar(raiz, arbol='worktree')` es context manager que devuelve Arbol con
raiz temporal, huella SHA-256, archivos (ruta POSIX → sha256/modo), origen y commit.
`huella_arbol(raiz, arbol='worktree')` devuelve identidad sin conservar temporal.
Los selectores reservados worktree/staged no prometen igualdad con HEAD y su
commit es None. Una ref literal se resuelve sin interpretación de shell.
ErrorArbol diagnostica entradas o materialización inseguras. La lectura segura
de worktree usa primitivas POSIX, probadas en macOS. No se verificó Windows.
El modelo cooperativo usa un escritor por worktree y no promete captura atómica
frente a otro proceso que escriba concurrentemente.

Worktree incluye tracked y untracked no ignorados. Tracked ignorados se conservan.
Staged lee el índice y REF lee objetos Git. No se usan checkout, filtros ni hooks.
Se rechazan gitlinks, conflictos y escapes. Enlaces relativos internos seguros
pueden preservarse. No se preservan enlaces absolutos que dependan del origen.

## Acuerdos y diferencias

`capturar_acuerdo(raiz, sesion, base=None)` devuelve schema, sesion, base,
ref_acuerdo, ruta_sesion, huella_acuerdo, huella_captura y datos normalizados.
Lee autoridad documental guardada en HEAD. Ref_acuerdo ancla esa proyección en
Git. base es el commit para comparar diferencias (HEAD por defecto). No escribe
ni inventa autorización. ErrorAcuerdo rechaza captura inválida.
Si la fuente declara una base distinta de HEAD, debe proporcionarse explícitamente
y coincidir con la base anclada. La huella de captura liga también base, ref y ruta.
La integridad cooperativa no constituye una firma del dueño.

En frontmatter de sesión: ejecucion_autorizada true, plan, funcionalidades y
acuerdo con referencia_pedido, funcionalidades, alcance y scaffold. Alcance es
un mapa de listas producto/pruebas/documentos/controles. Scaffold identifica
rutas concretas importables. La prosa autorizante se delimita con comentarios
`<!-- gobernanza:acuerdo -->` y `<!-- /gobernanza:acuerdo -->`.
Cambiar campos autorizantes invalida el acuerdo. Estado/resultados externos a
esa proyección no lo hacen. El snapshot se contrasta con su ancla, no se confía
en un diccionario alterable para ampliar alcance. Sigue siendo registro local
cooperativo, no una firma criptográfica del dueño.

`validar_cambios(raiz, sesion, acuerdo, arbol='worktree', fase='preparacion',
preparacion=None, dictamenes=())` devuelve diagnóstico y cambios contra base.
Fases: preparacion, ejecucion, entrega. Comprobar ambas rutas de renombres y
borrados. Producto espera preparación satisfecha. Adiciones puras de tests no
reducen obligaciones. Cambios sensibles requieren dictamen concreto con ruta,
base_sha256, nuevo_sha256 (None si borrado), revisor, motivo y decision
`conservar_obligacion`. No prueba identidad de quien opera la máquina.

`normalizar_autoridad(raiz_materializada, sesion)` y
`huella_obligaciones_materializadas(raiz_materializada)` reutilizan las mismas
reglas sobre una copia ya capturada, sin mezclar dos lecturas del origen.
`huella_obligaciones(raiz, arbol='worktree')` liga config, contratos, tests,
fixtures y controles, con autoridad normalizada de sesiones. Excluye producto
que no sea también prueba/control y salidas legítimas. Preparación utilizada en
ejecución debe contener preparacion_satisfecha true, huella_acuerdo y esta huella
vigentes. Una salida no puede ocultar entradas de pruebas, controles o solución.

## Unittest e informes

`verificar(raiz, sesion, arbol='staged', etapa='preparacion', acuerdo=None,
esperados_rojos={}, preparacion=None, dictamenes=(), destino=None, timeout=30)`.
Etapas preparacion/entrega. esperados_rojos mapea selector obligatorio a motivo
concreto. Preparación admite esos fallos de aserción descubiertos/ejecutados sin
errores adicionales, o paquete existente verde para conservación. No admite
omisiones, expected failures, cero casos o fallos de entorno como preparación.
La validez semántica del motivo conserva revisión cooperativa.

El adaptador solo soporta unittest con args declarados como lista. Usa proceso
aislado y checkout materializado. No importa producto del origen por PYTHONPATH.
El intérprete declarado debe resolver al Python ejecutor del kit. Otro intérprete
se rechaza explícitamente. quiet, verbose y buffer se aplican. Opciones no
soportadas se diagnostican. La versión efectivamente usada queda en el informe.
Compara casos obligatorios declarados con inventario real y resultados por caso.
Entrega requiere todos verdes. Timeout, ausencia, carga fallida o ejecución
incompleta quedan diagnosticados. Los informes registran comandos, exit real,
descubrimiento, ejecución, fallos, errores, omisiones y entorno.
Un método con varios subtests conserva todos los eventos y nunca degrada un
error a fallo de aserción. Así no se acepta como rojo válido un error previo.

`evidencia_vigente(raiz, informe, arbol='worktree')` contrasta integridad y entradas.
La huella de entrega incluye producto, tests/fixtures, configuración, contratos,
autoridad y reglas de selección. La de preparación conserva obligaciones sin
exigir que producto siga rojo. Cambios staged con HEAD idéntico invalidan el
contenido afectado. La versión real del núcleo ejecutor también queda ligada.
Solo se excluyen salidas declaradas que no solapen entradas. El cierre no debe
contener recursivamente su propio informe.

Los informes se generan fuera del checkout probado. destino, si se proporciona,
debe quedar fuera del origen y del checkout materializado. El caller puede
publicarlos después en las salidas declaradas. Sin destino se devuelve el informe
estructurado. Pruebas aprobadas y preparación satisfecha son campos diferentes.
Los resultados no conceden aceptación humana, cierre o integración.

## Perfil optativo de Heimdall

La entrada nativa es un objeto JSON de datos. Identifica `actor` y
`transaccion` por separado, `base` y `ref_acuerdo` por SHA exacto,
`version` y `cita` de la aprobación. Puede referir el relevo y las
fuentes de recibos y excepciones que correspondan. La consulta coteja
el acuerdo guardado, inventario, rutas y registros aplicables. El
responsable comprueba el pedido real en su fuente. Un dictamen de
prueba sensible se aporta por `entrada_nativa.excepciones`, con
revisor independiente, ruta, obligación y fuente guardada que liga
bytes anteriores y nuevos.

Para ejecución, la sección de verificación del plan aprobado declara
IDs de verificadores y requisitos externos. Proyectar requisitos
históricos exige cotejar su fuente y registrar la declaración bajo la
autoridad del folio correspondiente. El marcador de datos es único.
Ejemplo sintético:

```md
<!-- gobernanza:verificacion -->
{"unittest":["V-UNIDAD"],"externos":[{"id":"build","tipo":"build","comando":["npm","run","build"]}]}
<!-- /gobernanza:verificacion -->
```

`criterios` puede fijar referencias exactas `F-####@rN/CNN` del tramo
acordado. Si se omite, aplican los criterios de las F declaradas para
la sesión. La cabecera `Regresión` agrega las revisiones heredadas. Cada
regresión se enlaza a sus casos o a una suite nativa completa declarada
con `regresiones` y su inventario. Un verde previo sólo acredita cambios
de conservación con motivo y rutas declarados en `conservacion`.
Para conducta nueva, `esperados_rojos` liga `V-ID::selector` al motivo
concreto y la revisión comprueba que el fallo observado sea atribuible.

Un caso puede llevar varios comentarios nativos `# criterio: F-####/CNN`
junto al método. El informe los liga a revisión, selector, verificador,
ruta, línea y contenido. La identidad de ejecución es el par
verificador/selector. El inventario descubierto conserva los casos sin
criterio de la suite. La ejecución del kit usa unittest aprobado en
la copia materializada. Las suites nativas completas, build, operación
y resultado humano conservan sus fuentes separadas.

`entrada_nativa.evidencias` refiere cada registro con `ruta` canónica de
anexo y `sha256`. `ref` identifica el commit que lo contiene. Como
alternativa, `archivo` identifica la ruta efectiva absoluta de un JSON
regular fuera de los worktrees, conservado en el espacio de ensayo
autorizado. Sirve para cotejar la suite del HEAD sin ensuciar el índice
ni requerir un commit previo en main. Cada registro lleva proyecto, folio, ID, tipo, actor, fecha con zona,
referencia, versión del candidato o huella de entradas y estado.
Una comprobación técnica registra también comando, entorno, exit y
salida. El caso humano registra su criterio. La suite identifica
resultados por selector. Una ejecución de plataforma separada debe
coincidir con la omisión, caso, versión y plataforma que prevé el
acuerdo. Las salidas declaradas bajo los anexos del módulo quedan
fuera de la huella sólo cuando no solapan entradas protegidas.

La API devuelve el informe y la CLI puede emitirlo por stdout. El
escritor conserva el informe fuera del checkout y publica sólo
mediante las rutas nativas acordadas. Materializar separa las entradas.
El subproceso unittest conserva los permisos del entorno de ensayo.
