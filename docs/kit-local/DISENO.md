# Diseño del kit local de gobernanza

El kit versiona contratos y decisiones en Markdown y Git. Los campos JSON
declaran fuentes y relaciones verificables. El texto de un contrato o plan
sigue siendo libre. La persona que propone un cambio elige los vínculos y
justifica su pertinencia. El kit comprueba las referencias, la transición y
la autoridad aplicable antes de guardar una operación.

## Contratos y vínculos

| Documento | Función |
|---|---|
| Spec | Declara el contrato por versión y secciones. |
| Módulo | Agrupa capacidades y puede compartir un spec con otros módulos. |
| Funcionalidad | Fija una revisión, el módulo dueño, los criterios y las secciones aplicables. |
| Sesión | Trabaja sobre revisiones concretas de F y enlaza el plan, la autoridad y las evidencias. |
| Enmienda | Identifica qué secciones modifica y qué versión las incorpora. |

El registro explícito mantiene los documentos en `sdd/registro/`.
`sdd registrar` simula o aplica un lote anclado a un commit. La aplicación
conserva un recibo en Git. El índice se genera a partir de los documentos
y vínculos comprobados. Una consulta histórica toma sus fuentes del árbol
elegido. La carpeta `playground/` sirve para ideas y planes exploratorios.

## Acuerdo y pruebas

Una propuesta se registra como borrador. Su aprobación liga el plan y los
cambios autorizados. `iniciar` conserva la autoridad acordada, la preparación
identifica los casos que se van a verificar y la entrega requiere resultados
vigentes. Los casos declarados enlazan una revisión y un criterio.

```python
# gobernanza-test: {"id":"T-0001","criterio":"F-0001@r1/C01","verificador":"V-UNIDAD","selector":"test_tareas.TareasTests.test_crear"}
```

La entrega conserva resultados automáticos y los resultados humanos que solicita
el acuerdo. Git identifica la integración. El [formato del núcleo](FORMATO_NUCLEO.md)
describe los documentos y la API. Los formatos de [ejecución](FORMATO_EJECUCION.md)
y [entrega](FORMATO_ENTREGA.md) especifican las comprobaciones.
