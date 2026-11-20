---
name: navegar-gobernanza
description: Orienta la siguiente acción de una solicitud de gobernanza local con las fuentes, autoridad y evidencia del repositorio consumidor.
---

# Navegar la gobernanza local

Parte del pedido y la evidencia disponible. Si no identifican un objetivo, pregunta o hito concreto (por ejemplo, un saludo o «continuemos» sin referente), pide en una pregunta breve que se establezca o identifique. Espera la respuesta antes de buscar planes o abrir continuidad, fichas o referencias del kit.

Con un objetivo, determina **una siguiente acción** y su condición inmediata. Una consulta de sólo lectura puede responderse directamente con su fuente, sin abrir ficha. Cuando se identifica raíz o módulo, consulta las fuentes y el arranque de módulo que indique `AGENTS.md` según ese objetivo. Lee la continuidad pertinente y el estado del módulo primario según corresponda. Para trabajo funcional coteja la hoja de ruta declarada por el consumidor, si corresponde, con el estado y la evidencia de planes.

Elige sólo la entrada pertinente y consulta el ancla indicada.

- Pregunta acotada que necesita orientación adicional — [consulta](references/fases.md#consulta). Si la fuente directa basta, responde sin abrir ficha.
- El proyecto usa contratos y sesiones tipificados — [registro SDD](references/fases.md#registro-sdd).
- Falta definir el objeto o contrato — [insumo](references/fases.md#insumo-y-selección-de-módulo) o [contratación](references/fases.md#contratación).
- Falta plan — [planificación](references/fases.md#planificación). Plan completo por revisar o activar — [activación](references/fases.md#activación). Si falta aprobación, la siguiente puerta es obtenerla.
- Reanudar un hito — [reanudación](references/fases.md#reanudación). Retoma la puerta vigente y conserva las fases y aprobaciones que siguen satisfechas.
- Cambio autorizado — [ejecución](references/fases.md#ejecución-y-mantenimiento), incluyendo el preflight antes del efecto.
- Comprobar un criterio — [verificación](references/fases.md#verificación). Paquete revisado pendiente de decisión o merge — [integración](references/fases.md#integración). Merge realizado o cierre por preparar — [cierre](references/fases.md#cierre).
- Bloqueo o discrepancia — [recuperación](references/fases.md#recuperación). Si se pide, consulta [entrega](references/fases.md#entrega) o [despliegue](references/fases.md#despliegue).

Lee sólo la ficha y secciones que la acción necesite. Para una cita SDD usa `sdd seccion` con su versión exacta. Para otros perfiles, sigue el lector que indique `AGENTS.md`. Responde con la próxima lectura o instrucción y su condición inmediata. Para decisiones y diagnóstico consulta [autoridad y recuperación](references/autoridad-verificacion.md) en el apartado enlazado por la ficha.

Resuelve continuidad, módulos, contratos, planes y evidencia desde `raiz_trabajo`, la raíz Git del consumidor. Si el perfil divide gobierno y solución, usa las rutas y el dominio que indiquen `AGENTS.md` y las fuentes canónicas del consumidor. Si hay una guía propia, sigue la prioridad que establezca el consumidor. Para consultar el procedimiento del kit, sigue la skill operativa citada en el bloque gestionado de `AGENTS.md`. Su entrada indica cómo localizar el slot activo. El directorio `contenido/` de ese slot es `raiz_kit`, donde se resuelven sus formatos y documentación.

Contratos, planes y evidencia prevalecen sobre esta guía. Aplica el tratamiento de contradicciones del consumidor, incluida la marca `Inconsistente` en el artefacto dueño cuando corresponda. Comprueba la autoridad y la evidencia exigidas para cada decisión. Mantén los controles Git aplicables y usa sus vías autorizadas.
