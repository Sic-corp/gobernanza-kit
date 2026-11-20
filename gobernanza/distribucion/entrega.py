"""Construye una entrega transportable de un commit integrado, o un candidato de ensayo."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from ..nucleo.arboles import LectorArbol, commit_lectura
from ..nucleo.versiones import historial
from .paquete import crear_paquete


def crear_entrega(fuente, ref, destino, *, candidato=False):
    commit = commit_lectura(fuente, ref)
    version = None
    if not candidato:
        registro = next((v for v in historial(fuente) if v["commit"] == commit), None)
        if registro is None or registro["tipo"] == "linea_base":
            raise ValueError("El commit debe ser la integración de una versión registrada en main.")
        version = registro["version"]
    return _construir_entrega(fuente, commit, destino, version)


def crear_entrega_publica(fuente_publica, commit_publico, destino, *, version):
    """Empaqueta el árbol público cotejado por el exportador de la versión."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit_publico) or not re.fullmatch(r"V[0-9]+\.[0-9]{2}", version):
        raise ValueError("La entrega pública requiere una versión y un commit Git completos.")
    commit = commit_lectura(fuente_publica, commit_publico)
    return _construir_entrega(fuente_publica, commit, destino, version)


def _construir_entrega(fuente, commit, destino, version):
    lector = LectorArbol(fuente, commit)
    plantilla = lector.leer("gobernanza/distribucion/recursos/INSTALAR.py").decode("utf-8")
    marcador = "IDENTIDAD = None  # Sustituida al construir la entrega."
    if plantilla.count(marcador) != 1:
        raise ValueError("La entrada autónoma del commit tiene un formato desconocido.")
    destino = Path(destino).absolute()
    if destino.is_symlink() or destino.exists():
        raise ValueError(f"El destino ya existe: {destino}")
    info = dict(schema=1, producto="gobernanza-kit", version=version, commit=commit, paquetes={})
    with tempfile.TemporaryDirectory(dir=destino.parent, prefix=".entrega-") as temp:
        preparada = Path(temp) / "contenido"
        preparada.mkdir()
        for nombre, modo in (("paquete", None), ("paquete-ubicable", "ubicable")):
            paquete = preparada / nombre
            salida = crear_paquete(fuente, commit, paquete, modo=modo)
            if salida["codigo"]:
                raise ValueError(salida["errores"][0]["mensaje"])
            manifiesto = (paquete / "manifiesto.json").read_bytes()
            info["paquetes"][nombre] = dict(huella=salida["huella_paquete"],
                                            sha256=hashlib.sha256(manifiesto).hexdigest())
        (preparada / "entrega.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        (preparada / "instalar.py").write_text(plantilla.replace(marcador, "IDENTIDAD = " + repr(info)), encoding="utf-8")
        # mkdir exclusivo reserva el nombre sin reemplazar destinos concurrentes.
        destino.mkdir()
        try:
            preparada.replace(destino)
        except OSError:
            destino.rmdir()
            raise
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuente", required=True, type=Path)
    parser.add_argument("--ref", required=True, help="Referencia Git inmutable para la entrega")
    parser.add_argument("--salida", required=True, type=Path)
    parser.add_argument("--candidato", action="store_true", help="Ensayo sin asignación de versión integrada")
    args = parser.parse_args()
    try:
        info = crear_entrega(args.fuente, args.ref, args.salida, candidato=args.candidato)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
