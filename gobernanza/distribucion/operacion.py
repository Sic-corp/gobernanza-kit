"""Entrada a los cinco verbos desde el administrador de un slot activo."""

from pathlib import Path

from ..adaptadores import cli as nucleo
from ..nucleo.modelo import diagnostico, resultado
from .gestor import BASE, CAPACIDAD_AISLADA, inspeccionar


def ejecutar(raiz, argumentos, *, base_instalacion=None):
    if any(arg.startswith("--") and "--raiz".startswith(arg.partition("=")[0])
           for arg in argumentos if arg != "--"):
        return resultado("operar", [diagnostico(
            "USO_INVALIDO", "argumentos", "Una raíz por invocación",
            "Indica --raiz antes de operar.", "Consulta la ayuda del administrador local.")], codigo=2)

    estado = inspeccionar(raiz, base_instalacion=base_instalacion)
    if estado["codigo"]:
        return dict(estado, operacion="operar")
    activo = estado.get("activo")
    base = estado.get("base_instalacion", BASE)
    directorio = raiz.resolve() / base / "versiones"
    if activo is None or Path(__file__).resolve() != directorio / activo["huella_paquete"] / CAPACIDAD_AISLADA:
        return resultado("operar", [diagnostico(
            "RUNTIME_NO_ACTIVO", base, "Operación desde el slot activo del consumidor",
            "Este proceso no cargó la versión activa de la raíz indicada.",
            "Ejecuta el administrador local del consumidor.")])
    return nucleo.ejecutar([*argumentos, "--raiz", str(raiz.resolve())])
