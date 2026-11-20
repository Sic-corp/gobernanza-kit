# Inicio, cierre y comandos

La API Python y la CLI reutilizan los contratos y la evidencia de M-NUCLEO
y M-EJECUCION. Toda autorización se vincula al pedido real y al acuerdo en Git.
El agente integra mediante Git con la autorización aplicable.

## Inicio y registros

`iniciar(raiz, sesion, base=None)` usa captura del HEAD documental, la fija en
sesiones/estado/<id>/acuerdo.json y actualiza inicio/estado de la sesión mediante
commit documental acotado. Devuelve acuerdo, registro, ref_guardado e idempotente.
En una sesión tipificada, `iniciar` conserva el acuerdo y toma como fuente la
promoción registrada a `preparacion`. El Markdown de la sesión cambia mediante
operaciones SDD. El registro de inicio conserva la referencia de ese origen.
El commit del guardado se obtiene de Git y de `ref_guardado`. Repetir el mismo acuerdo
valida ancla/contenido y no crea commit ni reinicia fases. Un conflicto en rutas
propias, un recibo ajeno o un cambio de HEAD se rechaza sin perder trabajo.

`leer_inicio(raiz, sesion)` recupera el snapshot íntegro anclado. Los helpers
compartidos `guardar_documentos(raiz, documentos, mensaje, esperado=None,
refs_esperadas=None)` y
`escribir_json_seguro(raiz, ruta, datos)` hacen persistencia local acotada, sin
hooks/filtros, preservando entradas y blobs del staging ajeno. No se inventa autor
Git ni se modifica su configuración. Solo se opera la rama actual explícita.
La transacción comprueba las refs esperadas y avanza únicamente esa rama. Hay un
escritor por worktree: los fallos ordinarios restauran archivos/índice, sin promesa
de transacción física entre disco/índice/refs ante una caída del sistema.

`publicar_informe(raiz, sesion, informe, destino=None)` valida integridad/identidad
y guarda JSON como salida declarada. Por defecto sesiones/evidencias/<id>/.
Admite informes fallidos como diagnóstico, sin aprobarlos. No sobrescribe ajenos.
Registros derivados de inicio/cierre están fuera de entradas de producto.
Su autoridad se comprueba con el snapshot y Git, no por mera existencia del archivo.

## Entrega y confirmación

`evaluar_entrega(raiz, sesion, informe, arbol='HEAD', acuerdo=None,
preparacion=None, dictamenes=())` es solo lectura: reutiliza estructura, diff y
vigencia. Exige informe de entrega verde vigente. No ejecuta tests.

Casos humanos exigidos: acuerdo.casos_humanos con id/criterio. Resultados externos
a la autoridad: resultados_humanos con id, resultado pasa/falla, version igual a
huella_entradas del informe y referencia_comunicacion real. El núcleo comprueba
el registro cooperativo, no autentica al dueño ni inventa una respuesta.
Enmiendas requeridas se corresponden con enmiendas_incorporadas. Deuda requerida
con deuda_asignada y destino concreto a sesión/backlog. Pendientes sin resolver
bloquean.

`preparar_cierre(raiz, sesion, informe, destino='main', acuerdo=None,
preparacion=None, dictamenes=())` evalúa y guarda manifiesto/estado en commit propio,
sin actualizar destino. La primera vía exige destino ancestro de fuente y ramas
distintas. El candidato combinado tiene los mismos archivos que la fuente.
Si hay divergencia, se concilia fuera de esta operación antes de preparar.
No se ejecutan merge drivers. Ref/base/entradas se revalidan antes del guardado.

El manifiesto sesiones/estado/<id>/cierre.json conserva fuente_entrada anterior al
commit documental, destino/base, acuerdo e informe con integridad, sin SHA propio.
La salida devuelve cierre y commit_cierre. La punta preparada se deriva del commit
creador del manifiesto. Sus entradas verificadas deben seguir iguales.

`confirmar_cierre(raiz, sesion, integracion, cierre=None, destino='main', cache=True)`
exige integración local autorizada, merge real con exactamente dos padres en orden
[baseDestino, fuentePreparada], árbol completo idéntico y SHA alcanzable desde el
destino. Fast-forward, fuente posterior, base divergente y cambios de base/resoluciones
inesperadas se rechazan. Solo actualiza cache descartable en metadatos Git. No otro commit en
main.

## Registro de versiones

En el perfil estándar, `"versionado_aplicacion": true` habilita el registro de
entregas en `gobernanza/config.json`. El acuerdo del cierre abarca
`sdd/entregas/aplicacion.json`. `cerrar --preparar` agrega el registro al mismo
guardado del candidato y `cerrar --confirmar` comprueba que la integración lo
conserva. El historial de primer padre en la rama destino identifica el SHA
exacto de cada V.

Una entrega que cambia rutas de solución aumenta el contador una vez. El
registro contiene la V anterior, la sesión, las revisiones entregadas, los
cambios atribuidos a sus dueños y la evidencia. Si cambia la base, concilia y
comprueba el candidato antes de integrar. Un cierre de gestión conserva la V
vigente. La primera entrega versionada ancla `V1.00` en su base y registra
`V1.01` en la integración. Los antecedentes se consultan por sus refs y
evidencias originales.

Para abrir una serie estable, usa una sesión dedicada con autorización del dueño.
En `acuerdo.version_aplicacion` registra `tipo: "estable"`, `serie`, `objetivo`,
`requisitos` como lista de referencias mínimas `F-####@rN`, y `autorizacion` como
referencia a la autorización real del corte. Si se declaran `criterios`, son
referencias `F-####@rN/CNN`. El corte comprueba las revisiones integradas y la
evidencia vigente de los criterios requeridos sobre su candidato. Al integrar
el corte se registra la V de la nueva serie, por ejemplo `V2.00`.

El número V identifica una entrega de solución. Un paquete instalable sigue
identificado por su SHA fuente y huella. Para revisar el historial y la traza de
una F, usa el [contexto integrado](FORMATO_NUCLEO.md#contexto-integrado).

## Adaptadores públicos

`python3 -m gobernanza` ofrece `contexto`, `validar`, `iniciar`, `verificar`,
`cerrar` y `sdd`. Usa la ayuda general o por verbo. `--raiz` indica el
consumidor y `--json` devuelve operación, estado, código, resumen y errores.
Los comandos tipificados y sus ejemplos están en el
[formato del núcleo](FORMATO_NUCLEO.md#registro-documental-sdd). Sale 0 si satisface, 1 por condición incumplida
y 2 por uso inválido. Error interno impide éxito y conserva diagnóstico.

Contexto ofrece `--sesion`, `--funcionalidad` y `--ruta`. `--integrada` se usa
con una F y `--version` admite una consulta sola o filtrada por F o ruta.
Validar admite
--arbol worktree/staged/REF y --modo borrador/trabajo/entrega. Borrador es lectura
estructural, trabajo reutiliza validar_cambios, entrega evaluar_entrega con informe.
Los archivos --acuerdo/--preparacion/--dictamenes/--informe son JSON, nunca código.
--base permite capturar la base declarada cuando no se proporciona snapshot.
--fase concreta preparación/ejecución al validar trabajo, sin conceder autoridad.

Verificar usa el runner existente; --etapa preparacion/entrega, --arbol y
--esperados-rojos JSON selector→motivo. Publica un informe real en salidas declaradas
después de generarlo fuera de la copia probada; --salida permite destino explícito.
Cerrar distingue --preparar y --confirmar --integracion SHA. No realiza el merge.
Las opciones se detallan en ayuda. No hay comandos extras para ramas/guardados.

## Perfil optativo de Heimdall

Los cinco verbos seleccionan el perfil por la configuración guardada.
Con `heimdall-v2`, la API y la CLI planifican y cotejan. El escritor
aplica cada lote documentado y usa el Git nativo con los controles
vigentes. Los resultados de verificación van por stdout. El núcleo
reconoce archivos de datos JSON y comprueba procedencia antes de
usarlos. El modo original conserva su interfaz.

| Operación | Entrada y salida del perfil |
|---|---|
| `iniciar --sesion FOLIO --entrada-nativa ENTRADA --json` | Para activar un Borrador guardado, el escritor aporta `imagenes` por ruta exacta, con `modo` y `texto` UTF-8. Devuelve lote y precondiciones de activación. Para un Activo coteja ancla y retoma. |
| `validar --modo trabajo --arbol staged --planificar-guardado --sesion FOLIO --entrada-nativa ENTRADA --json` | Coteja alcance, claims, índice y preparación. Devuelve lote de guardado con hashes previo/nuevo y huellas de obligación y acuerdo. Usar `--preparacion` cuando aplique. |
| `validar --modo trabajo --plan-guardado LOTE --arbol ARBOL --sesion FOLIO --entrada-nativa ENTRADA --json` | Comprueba el lote exacto contra stage o el commit observado. Acepta el objeto lote o la respuesta que lo contiene. Un cierre usa también `integracion` en la entrada. |
| `verificar --etapa ETAPA --arbol ARBOL --sesion FOLIO --entrada-nativa ENTRADA --json` | Ejecuta casos declarados y devuelve informe. Las evidencias externas se comprueban con las fuentes y el candidato descritos en el formato de ejecución. |
| `cerrar --preparar --sesion FOLIO --informe INFORME --entrada-nativa ENTRADA --json` | Verifica un candidato Activo con informe vigente. La entrada identifica rama fuente, integrador, topología por Git, rutas de cierre y si procede la vía póstuma. La respuesta identifica el paquete revisable y el estado de su permiso separado. |
| `cerrar --confirmar --sesion FOLIO --integracion SHA --entrada-nativa ENTRADA --json` | Coteja merge, permiso y el registro `suite` sobre main. Permite preparar el cotejo del lote de cierre staged mediante `comprobar_cierre` y cotejar el commit mediante `commit_cierre` y `lote_cierre`. |

Inicio y guardado fijan raíz, common-dir, rama, identidad documental,
padre y todas las rutas. Para guardar, cotejar inmediatamente el
índice y cualquier cambio entre éste y el worktree. Tras Git ordinario,
comprobar que el commit observado contiene el mismo lote. Repetir la
conciliación exacta conserva resultado y trabajo ajeno.

La integración usa permiso nativo por actor y folio en
`.heimdall/runtime/integration/<actor>/<folio>/heimdall.json`.
Sólo la aprobación del paquete concreto habilita el inicio del merge.
El cierre estándar exige dos padres en orden, árbol aprobado, suite
verde sobre el HEAD que precede al cierre, mensaje exacto y destinos
de plan, estado y evidencia. La continuidad se incluye si consta en
el permiso. La confirmación examina los SHAs observados. Permanece
en lectura y deja la ejecución de Git y la emisión del permiso al
flujo nativo. La vía póstuma S exige worktrees separados. La
discrepancia de G póstuma requiere conciliación contractual antes de
operar. Cierre conjunto o tardío y resoluciones de conflicto
conservan su procedimiento nativo.
