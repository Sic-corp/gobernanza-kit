# Ejemplo de adopción del kit

Usa un repositorio Git descartable para conocer el flujo. El ejemplo trata
de una lista de tareas y usa identidades ficticias.

1. Instala el kit en la modalidad que corresponda. Revisa el bloque gestionado
   de `AGENTS.md` y la guía instalada.
2. Crea un módulo `M-TAREAS` y un contrato `SPEC-0001@v1` con la sección
   explícita `ALTA`. Registra la funcionalidad `F-0001@r1` con un criterio
   `C01` y la cita `SPEC-0001@v1#ALTA`.
3. Prepara un plan en Markdown que describe cómo crear una tarea. Registra
   la sesión `S01-01` como borrador citando esa revisión de F.
4. Abre una consulta de la sección y una traza de la sesión. Comprueba que
   el fragmento y el texto del plan coinciden con los datos registrados.
5. Si vas a ejecutar el plan, guarda su aprobación real y promueve la sesión
   a preparación. Inicia la sesión con el acuerdo que corresponda.
6. Vincula la prueba al criterio, ejecuta la preparación, construye el cambio
   y verifica la entrega. Cierra y confirma la integración cuando se cumplan
   las condiciones del acuerdo.

El [formato SDD](FORMATO_NUCLEO.md#registro-documental-sdd) contiene las
operaciones y un ejemplo de lote. El [formato de ejecución](FORMATO_EJECUCION.md)
explica las huellas, fases y resultados. El [formato de entrega](FORMATO_ENTREGA.md)
describe el cierre y la confirmación.
