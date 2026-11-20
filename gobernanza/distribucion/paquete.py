"""Paquetes locales inmutables desde REF Git; F-0109@r1."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

from ..nucleo.arboles import _clave_portable, _leer_trabajo, _ruta, materializar
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import _escribir_bytes, _json
from ..nucleo.modelo import diagnostico, resultado
from ..nucleo.verificacion import _hash


COMPATIBILIDAD = {"bootstrap": 1, "consumidor": 1, "python_minimo": "3.10", "plataforma": "posix"}
DOCUMENTOS = ("DISENO.md", "SESION_PILOTO.md", "FORMATO_NUCLEO.md", "FORMATO_EJECUCION.md",
              "FORMATO_ENTREGA.md", "FORMATO_DISTRIBUCION.md", "GUIA.md")
MARCADOR = "contenido/gobernanza/nucleo/_version_kit.py"
CAPACIDAD_UBICABLE = "contenido/gobernanza/distribucion/entrada_ubicable.py"
NAVEGACION = (
    "contenido/skill/navegar-gobernanza/SKILL.md",
    "contenido/skill/navegar-gobernanza/references/autoridad-verificacion.md",
    "contenido/skill/navegar-gobernanza/references/fases.md",
)
RECURSOS = {
    "INICIO.py": "entradas/inicio.py", "GESTIONAR.py": "entradas/gestionar.py",
    "SKILL_ENTRADA.md": "entradas/SKILL.md", "SKILL.md": "contenido/skill/SKILL.md",
    "GUIA.md": "contenido/docs/kit-local/GUIA.md",
}
REQUERIDOS = {
    "contenido/gobernanza/__init__.py", "contenido/gobernanza/__main__.py",
    "contenido/gobernanza/nucleo/runner_unittest.py", MARCADOR,
    "contenido/gobernanza/distribucion/__init__.py", "contenido/gobernanza/distribucion/__main__.py",
    "contenido/gobernanza/distribucion/paquete.py", "contenido/gobernanza/distribucion/gestor.py",
    "contenido/gobernanza/distribucion/cli.py", "contenido/skill/SKILL.md",
    *RECURSOS.values(), *("contenido/docs/kit-local/" + d for d in DOCUMENTOS),
    "contenido/gobernanza/adaptadores/__init__.py", "contenido/gobernanza/adaptadores/cli.py",
    *("contenido/gobernanza/nucleo/" + n for n in (
        "__init__.py", "acuerdos.py", "arboles.py", "cierre.py", "contexto.py", "documentos.py",
        "inicio.py", "modelo.py", "runner_unittest.py", "validacion.py", "verificacion.py")),
}


class ErrorPaquete(ValueError):
    pass


def _marca(commit, inventario):
    return ('"""Identidad generada del kit completo; sin hashes recursivos."""\n'
            + f'FUENTE_COMMIT = "{commit}"\n'
            + f'HUELLA_CONTENIDO = "{_hash(inventario)}"\n').encode("utf-8")


def _ruta_archivo(ruta):
    _ruta(ruta)
    permitida = (ruta in REQUERIDOS or ruta in NAVEGACION or (
        ruta.startswith("contenido/gobernanza/") and ruta.endswith(".py")
        and "/recursos/" not in ruta and "/sesiones/" not in ruta))
    if not permitida:
        raise ErrorPaquete(f"Ruta fuera del contenido gestionado: {ruta}")
    return ruta


def _validar_navegacion(archivos):
    presentes = set(NAVEGACION).intersection(archivos)
    if presentes and len(presentes) != len(NAVEGACION):
        raise ErrorPaquete("El complemento de navegación requiere su guía y ambas referencias.")


def _inventario(archivos):
    return {ruta: {"sha256": hashlib.sha256(contenido).hexdigest(), "modo": modo}
            for ruta, (modo, contenido) in sorted(archivos.items())}


def _leer_regular(raiz, ruta):
    datos = _leer_trabajo(raiz, ruta)
    if datos is None or datos[0] not in {"100644", "100755"}:
        raise ErrorPaquete(f"Archivo regular ausente o enlazado: {ruta}")
    return datos


def _recorrer(raiz):
    archivos, directorios = set(), set()
    for actual, carpetas, hojas in os.walk(raiz, followlinks=False):
        for nombre in carpetas + hojas:
            p = Path(actual) / nombre
            ruta = p.relative_to(raiz).as_posix()
            _ruta(ruta)
            if p.is_symlink():
                raise ErrorPaquete(f"El paquete no permite enlaces: {ruta}")
            if p.is_dir():
                directorios.add(ruta)
            elif p.is_file():
                archivos.add(ruta)
            else:
                raise ErrorPaquete(f"Objeto no regular en paquete: {ruta}")
    claves = {}
    for ruta in sorted(archivos | directorios):
        clave = _clave_portable(ruta)
        if clave in claves:
            raise ErrorPaquete(f"Aliases NFC/casefold en paquete: {ruta}")
        claves[clave] = ruta
    return archivos, directorios


def _validar(paquete):
    original = Path(paquete)
    if original.is_symlink():
        raise ErrorPaquete("La raíz del paquete no puede ser un enlace.")
    raiz = original.resolve(strict=True)
    if not raiz.is_dir():
        raise ErrorPaquete("El paquete debe ser un directorio.")
    archivos, directorios = _recorrer(raiz)
    modo_manifiesto, contenido_manifiesto = _leer_regular(raiz, "manifiesto.json")
    if modo_manifiesto != "100644":
        raise ErrorPaquete("El manifiesto requiere modo regular 100644.")
    m = json_estricto(contenido_manifiesto.decode("utf-8"))
    claves = {"schema", "producto", "version", "fuente_commit", "compatibilidad", "archivos", "huella_paquete"}
    if not isinstance(m, dict) or set(m) != claves or type(m.get("schema")) is not int or m["schema"] != 1:
        raise ErrorPaquete("Manifiesto del esquema 1 inválido o con campos desconocidos.")
    commit = m["fuente_commit"]
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None or m["version"] != commit:
        raise ErrorPaquete("La versión debe identificar exactamente el commit fuente.")
    compatibilidad = m["compatibilidad"]
    if (m["producto"] != "gobernanza-kit" or not isinstance(compatibilidad, dict)
            or set(compatibilidad) != set(COMPATIBILIDAD)
            or any(type(compatibilidad[k]) is not type(v) or compatibilidad[k] != v
                   for k, v in COMPATIBILIDAD.items())):
        raise ErrorPaquete("Producto o protocolo de compatibilidad no soportados.")
    if os.name != "posix" or sys.version_info < (3, 10):
        raise ErrorPaquete("Se requiere POSIX y Python 3.10 o posterior.")
    if not isinstance(m["archivos"], dict) or not REQUERIDOS.issubset(m["archivos"]):
        raise ErrorPaquete("El inventario no contiene el runtime, entradas y referencias completos.")
    _validar_navegacion(m["archivos"])
    normalizadas = set()
    for ruta, meta in m["archivos"].items():
        _ruta_archivo(ruta)
        clave = _clave_portable(ruta)
        if clave in normalizadas:
            raise ErrorPaquete(f"Aliases de ruta en manifiesto: {ruta}")
        normalizadas.add(clave)
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "modo"}
                or meta["modo"] not in {"100644", "100755"}
                or not isinstance(meta["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]) is None):
            raise ErrorPaquete(f"Metadatos de archivo inválidos: {ruta}")
    if archivos != set(m["archivos"]) | {"manifiesto.json"}:
        raise ErrorPaquete("El inventario no coincide exactamente con los archivos del paquete.")
    if any(not any(r.startswith(d + "/") for r in archivos) for d in directorios):
        raise ErrorPaquete("El paquete contiene directorios adicionales vacíos.")
    for ruta, meta in m["archivos"].items():
        modo, contenido = _leer_regular(raiz, ruta)
        if modo != meta["modo"] or hashlib.sha256(contenido).hexdigest() != meta["sha256"]:
            raise ErrorPaquete(f"Integridad o modo distintos del manifiesto: {ruta}")
    sin_marca = {k: v for k, v in m["archivos"].items() if k != MARCADOR}
    if _leer_regular(raiz, MARCADOR)[1] != _marca(commit, sin_marca):
        raise ErrorPaquete("La marca de versión no corresponde al commit y contenido completo.")
    if m["huella_paquete"] != _hash({k: v for k, v in m.items() if k != "huella_paquete"}):
        raise ErrorPaquete("La huella del manifiesto no corresponde al paquete.")
    return raiz, m


def _salida(operacion, paquete=None, manifiesto=None, error=None):
    errores = [] if error is None else [diagnostico("PAQUETE_INVALIDO", str(paquete) if paquete is not None else ".",
        "Paquete íntegro del protocolo 1 desde REF explícita", str(error) or type(error).__name__,
        "Conserva el origen y el destino; corrige la REF, el manifiesto o las rutas antes de continuar.")]
    r = resultado(operacion, errores)
    r.update(paquete=str(paquete) if error is None and paquete is not None else None,
             manifiesto=manifiesto if error is None else None,
             huella_paquete=manifiesto["huella_paquete"] if error is None and manifiesto is not None else "")
    return r


def validar_paquete(paquete):
    """Solo lectura estática: no importa ni ejecuta Python del paquete."""
    try:
        raiz, m = _validar(paquete)
        return _salida("validar_paquete", raiz, m)
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        return _salida("validar_paquete", paquete, error=exc)


def crear_paquete(fuente, ref, destino, *, modo=None):
    """Resuelve una REF una vez y exporta solo runtime y assets declarados."""
    creado = False
    salida = None
    try:
        if not isinstance(ref, str) or not ref or ref in {"worktree", "staged"}:
            raise ErrorPaquete("Se requiere REF Git explícita; no se empaqueta worktree ni staged.")
        if modo not in (None, "ubicable"):
            raise ErrorPaquete("Modo de empaquetado inválido; usa ubicable o el predeterminado.")
        pedido = Path(destino).absolute()
        if pedido.exists() or pedido.is_symlink():
            raise ErrorPaquete("El destino del paquete debe ser nuevo; no se sobrescribe contenido existente.")
        salida = pedido.parent.resolve(strict=True) / pedido.name
        # Toda lectura fuente procede de la instantánea Git, no del checkout vivo.
        with materializar(fuente, ref) as vista:
            if "gobernanza/nucleo/_version_kit.py" in vista.archivos:
                raise ErrorPaquete("El commit fuente contiene el marcador reservado generado.")
            archivos = {}
            for ruta in vista.archivos:
                if (ruta.startswith("gobernanza/") and ruta.endswith(".py")
                        and not ruta.startswith(("gobernanza/sesiones/", "gobernanza/distribucion/recursos/"))):
                    archivos["contenido/" + ruta] = _leer_regular(vista.raiz, ruta)
            for nombre in DOCUMENTOS:
                if nombre != "GUIA.md":
                    ruta = "docs/kit-local/" + nombre
                    archivos["contenido/" + ruta] = _leer_regular(vista.raiz, ruta)
            for recurso, ruta in RECURSOS.items():
                if modo == "ubicable" and recurso == "SKILL_ENTRADA.md":
                    recurso = "SKILL_ENTRADA_UBICABLE.md"
                archivos[ruta] = _leer_regular(vista.raiz, "gobernanza/distribucion/recursos/" + recurso)
            for ruta in NAVEGACION:
                recurso = "gobernanza/distribucion/recursos/" + ruta.removeprefix("contenido/skill/")
                if recurso in vista.archivos:
                    archivos[ruta] = _leer_regular(vista.raiz, recurso)
            _validar_navegacion(archivos)
            if modo == "ubicable" and CAPACIDAD_UBICABLE not in archivos:
                raise ErrorPaquete("La REF carece de la entrada de administración ubicable.")
            inventario = _inventario(archivos)
            archivos[MARCADOR] = ("100644", _marca(vista.commit, inventario))
            m = dict(schema=1, producto="gobernanza-kit", version=vista.commit, fuente_commit=vista.commit,
                     compatibilidad=dict(COMPATIBILIDAD), archivos=_inventario(archivos))
            m["huella_paquete"] = _hash(m)
            if not REQUERIDOS.issubset(archivos):
                raise ErrorPaquete("La REF no contiene el runtime y referencias completos.")
        salida.mkdir(mode=0o755)
        creado = True
        for ruta, (modo, contenido) in sorted(archivos.items()):
            _escribir_bytes(salida, ruta, contenido, exclusivo=True, modo=modo)
        _escribir_bytes(salida, "manifiesto.json", _json(m), exclusivo=True)
        _, comprobado = _validar(salida)
        return _salida("crear_paquete", salida, comprobado)
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        if creado:
            shutil.rmtree(salida)
        return _salida("crear_paquete", destino, error=exc)
