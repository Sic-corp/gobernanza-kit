"""Entrada autónoma para una instalación ubicada por el consumidor."""

import sys

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata


SKILL_UBICABLE = """---
name: gobernanza-local
description: Trabajar con la versión local del kit que ha instalado este repositorio.
---

# Gobernanza local del repositorio

Identifica el checkout Git del consumidor y lee el archivo hermano
`activo.json`. El campo `huella_paquete` identifica la versión bajo
`versiones/<huella_paquete>/`. Sigue su guía en
`contenido/skill/SKILL.md`.

Desde la raíz del consumidor usa `python3 -I RUTA/gestionar.py operar --help`,
donde RUTA es la ubicación de este directorio en el repositorio. Para
consultar la instalación usa la misma entrada con el verbo `estado`.

Si hay una transacción pendiente en
`gobernanza/.rutas-kit-transaccion.json` del consumidor, usa
`gestionar.py recuperar`. El estado y las reglas de trabajo del proyecto
siguen siendo los de su política y sus sesiones vigentes.
"""


_COMPAT = {"bootstrap": 1, "consumidor": 1, "python_minimo": "3.10", "plataforma": "posix"}
# La verificación se ejecuta antes de importar el paquete, como en la entrada v1.
_CAPACIDAD = "contenido/gobernanza/distribucion/entrada_ubicable.py"
_DIARIO = "gobernanza/.rutas-kit-transaccion.json"
_MARCA = "contenido/gobernanza/nucleo/_version_kit.py"
_NAVEGACION = {
    "contenido/skill/navegar-gobernanza/SKILL.md",
    "contenido/skill/navegar-gobernanza/references/autoridad-verificacion.md",
    "contenido/skill/navegar-gobernanza/references/fases.md",
}
_REQUERIDOS = {
    _CAPACIDAD,
    "contenido/gobernanza/__init__.py", "contenido/gobernanza/__main__.py",
    "contenido/gobernanza/adaptadores/__init__.py", "contenido/gobernanza/adaptadores/cli.py",
    *("contenido/gobernanza/nucleo/" + n for n in (
        "__init__.py", "acuerdos.py", "arboles.py", "cierre.py", "contexto.py", "documentos.py",
        "inicio.py", "modelo.py", "runner_unittest.py", "validacion.py", "verificacion.py", "_version_kit.py")),
    *("contenido/gobernanza/distribucion/" + n for n in (
        "__init__.py", "__main__.py", "cli.py", "gestor.py", "paquete.py")),
    *("contenido/docs/kit-local/" + n for n in (
        "DISENO.md", "SESION_PILOTO.md", "FORMATO_NUCLEO.md", "FORMATO_EJECUCION.md",
        "FORMATO_ENTREGA.md", "FORMATO_DISTRIBUCION.md", "GUIA.md")),
    "contenido/skill/SKILL.md", "entradas/inicio.py", "entradas/gestionar.py", "entradas/SKILL.md",
}


def _hash(datos):
    texto = json.dumps(datos, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _json(texto):
    def pares(valores):
        salida = {}
        for clave, valor in valores:
            if clave in salida:
                raise ValueError("Clave JSON duplicada")
            salida[clave] = valor
        return salida
    def constante(valor):
        raise ValueError("Constante JSON inválida")
    return json.loads(texto, object_pairs_hook=pares, parse_constant=constante)


def _clave(ruta):
    return unicodedata.normalize("NFC", ruta).casefold()


def _ruta(ruta):
    if (not isinstance(ruta, str) or not ruta or "\\" in ruta or "\x00" in ruta
            or not PurePosixPath(ruta).parts
            or PurePosixPath(ruta).is_absolute() or ".." in PurePosixPath(ruta).parts
            or PurePosixPath(ruta).as_posix() != ruta
            or any(_clave(p) == ".git" for p in PurePosixPath(ruta).parts)):
        raise ValueError("Ruta local insegura")
    return ruta


def _leer(raiz, relativa):
    partes = PurePosixPath(_ruta(relativa)).parts
    abiertos = []
    try:
        fd = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        abiertos.append(fd)
        for parte in partes[:-1]:
            fd = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            abiertos.append(fd)
        previo = os.stat(partes[-1], dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(previo.st_mode):
            raise ValueError("Archivo local no regular")
        archivo = os.open(partes[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        abiertos.append(archivo)
        estado = os.fstat(archivo)
        if not stat.S_ISREG(estado.st_mode):
            raise ValueError("Archivo local no regular")
        with os.fdopen(os.dup(archivo), "rb") as flujo:
            datos = flujo.read()
        return ("100755" if estado.st_mode & 0o111 else "100644"), datos
    finally:
        for fd in reversed(abiertos):
            os.close(fd)


def _existe(raiz, relativa):
    try:
        _leer(raiz, relativa)
        return True
    except FileNotFoundError:
        return False


def _selector(datos):
    if (not isinstance(datos, dict)
            or set(datos) != {"schema", "huella_paquete", "version", "fuente_commit"}
            or type(datos["schema"]) is not int or datos["schema"] != 1
            or not isinstance(datos["huella_paquete"], str)
            or re.fullmatch(r"[0-9a-f]{64}", datos["huella_paquete"]) is None
            or not isinstance(datos["fuente_commit"], str)
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", datos["fuente_commit"]) is None
            or datos["version"] != datos["fuente_commit"]):
        raise ValueError("Selector de versión inválido")
    return datos


def _slot(raiz, base, selector, *, requiere_navegacion=False):
    _selector(selector)
    relativa = f"{base}/versiones/{selector['huella_paquete']}"
    # Esta apertura comprueba también todos los ancestros antes del inventario.
    modo, datos = _leer(raiz, relativa + "/manifiesto.json")
    if modo != "100644":
        raise ValueError("Modo de manifiesto inválido")
    m = _json(datos.decode("utf-8"))
    if (not isinstance(m, dict) or set(m) != {"schema", "producto", "version", "fuente_commit", "compatibilidad", "archivos", "huella_paquete"}
            or type(m["schema"]) is not int or m["schema"] != 1 or m["producto"] != "gobernanza-kit"):
        raise ValueError("Manifiesto no reconocido")
    compat = m["compatibilidad"]
    if (not isinstance(compat, dict) or set(compat) != set(_COMPAT)
            or any(type(compat[k]) is not type(v) or compat[k] != v for k, v in _COMPAT.items())
            or os.name != "posix" or sys.version_info < (3, 10)):
        raise ValueError("Kit incompatible con esta entrada o plataforma")
    if any(m[k] != selector[k] for k in ("huella_paquete", "version", "fuente_commit")):
        raise ValueError("La versión seleccionada no coincide con su manifiesto")
    if not isinstance(m["archivos"], dict) or not _REQUERIDOS.issubset(m["archivos"]):
        raise ValueError("Runtime o referencias incompletos")
    navegacion = _NAVEGACION.intersection(m["archivos"])
    if (navegacion or requiere_navegacion) and navegacion != _NAVEGACION:
        raise ValueError("Guía de navegación o referencias incompletas")
    vistos, claves = set(), set()
    slot = raiz / relativa
    for directorio, carpetas, hojas in os.walk(slot, followlinks=False):
        for nombre in carpetas + hojas:
            p = Path(directorio) / nombre
            ruta = p.relative_to(slot).as_posix()
            _ruta(ruta)
            clave = _clave(ruta)
            if clave in claves or p.is_symlink():
                raise ValueError("Alias o enlace no permitido en la versión instalada")
            claves.add(clave)
            if p.is_dir():
                if not any(r.startswith(ruta + "/") for r in m["archivos"]):
                    raise ValueError("Directorio adicional en la versión instalada")
            elif p.is_file():
                vistos.add(ruta)
            else:
                raise ValueError("Objeto no regular en la versión instalada")
    if vistos != set(m["archivos"]) | {"manifiesto.json"}:
        raise ValueError("Inventario instalado distinto del manifiesto")
    normalizadas = set()
    for ruta, meta in m["archivos"].items():
        _ruta(ruta)
        if not (ruta in _REQUERIDOS or ruta in _NAVEGACION or (
                ruta.startswith("contenido/gobernanza/") and ruta.endswith(".py")
                and "/recursos/" not in ruta and "/sesiones/" not in ruta)):
            raise ValueError("Ruta fuera del contenido permitido")
        clave = _clave(ruta)
        if clave in normalizadas:
            raise ValueError("Aliases en el manifiesto")
        normalizadas.add(clave)
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "modo"}
                or meta["modo"] not in {"100644", "100755"}
                or not isinstance(meta["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]) is None):
            raise ValueError("Metadatos de archivo inválidos")
        modo, contenido = _leer(raiz, relativa + "/" + ruta)
        if modo != meta["modo"] or hashlib.sha256(contenido).hexdigest() != meta["sha256"]:
            raise ValueError("Integridad del kit alterada: " + ruta)
    sin_marca = {k: v for k, v in m["archivos"].items() if k != _MARCA}
    marca = ('"""Identidad generada del kit completo; sin hashes recursivos."""\n'
             + 'FUENTE_COMMIT = "' + m["fuente_commit"] + '"\n'
             + 'HUELLA_CONTENIDO = "' + _hash(sin_marca) + '"\n').encode("utf-8")
    if _leer(raiz, relativa + "/" + _MARCA)[1] != marca:
        raise ValueError("Marca de versión incoherente")
    if m["huella_paquete"] != _hash({k: v for k, v in m.items() if k != "huella_paquete"}):
        raise ValueError("Huella de manifiesto incorrecta")
    return slot


def _ubicacion():
    archivo = Path(os.path.abspath(__file__))
    for ancestro in archivo.parents:
        try:
            info = (ancestro / ".git").lstat()
        except FileNotFoundError:
            continue
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("El marcador Git debe ser un directorio o archivo regular")
        raiz = ancestro.resolve(strict=True)
        relativa = _ruta(archivo.relative_to(ancestro).as_posix())
        break
    else:
        raise ValueError("La entrada debe estar dentro de un checkout Git")

    partes = PurePosixPath(relativa).parts
    huella = None
    sufijo = PurePosixPath(_CAPACIDAD).parts
    if partes[-1] == "gestionar.py":
        base = "/".join(partes[:-1])
    elif (len(partes) > len(sufijo) + 2 and partes[-len(sufijo):] == sufijo
          and partes[-len(sufijo) - 2] == "versiones"):
        huella = partes[-len(sufijo) - 1]
        if re.fullmatch(r"[0-9a-f]{64}", huella) is None:
            raise ValueError("Huella inválida en la entrada de recuperación")
        base = "/".join(partes[:-len(sufijo) - 2])
    else:
        raise ValueError("Ubicación de entrada no reconocida")
    return raiz, _ruta(base), relativa, huella


def _argumentos(raiz, argv):
    posiciones = []
    for i, argumento in enumerate(argv):
        nombre, separador, valor = argumento.partition("=")
        if nombre != "--raiz":
            if nombre.startswith("--") and nombre != "--" and "--raiz".startswith(nombre):
                raise ValueError("Usa --raiz sin abreviar")
            continue
        if separador:
            posiciones.append((i, nombre + "=", valor))
        else:
            if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                raise ValueError("--raiz necesita un directorio")
            posiciones.append((i + 1, "", argv[i + 1]))
    if not posiciones:
        return ["--raiz", str(raiz), *argv]
    if len(posiciones) != 1:
        raise ValueError("Indica como máximo una raíz explícita")
    i, prefijo, valor = posiciones[0]
    if not valor or Path(valor).resolve() != raiz:
        raise ValueError("--raiz debe coincidir con el checkout de esta entrada")
    argumentos = list(argv)
    argumentos[i] = prefijo + str(raiz)
    return argumentos


def _selector_de_respaldo(raiz, base, huella):
    manifiesto = _json(_leer(raiz, f"{base}/versiones/{huella}/manifiesto.json")[1].decode("utf-8"))
    return _selector(dict(schema=1, huella_paquete=huella, version=manifiesto["version"],
                          fuente_commit=manifiesto["fuente_commit"]))


def _seleccion_admin(raiz, base, huella):
    if _existe(raiz, _DIARIO):
        d = _json(_leer(raiz, _DIARIO)[1].decode("utf-8"))
        fija = isinstance(d, dict) and d.get("ruta_fija") is True
        modos = ("estandar", "aislado", "ubicable") if fija else ("ubicable",)
        if (not isinstance(d, dict) or type(d.get("schema")) is not int or d["schema"] != 1
                or (fija and base != "gobernanza/kit-local")
                or d.get("modo") not in modos or d.get("base_instalacion") != base
                or not isinstance(d.get("id"), str) or re.fullmatch(r"[0-9a-f]{32}", d["id"]) is None
                or d.get("accion") not in {"instalar", "actualizar"}
                or d.get("fase") not in {"preparado", "version_lista", "entradas_publicadas",
                                         "selector_publicado", "purga_confirmada"}
                or not isinstance(d.get("rutas"), dict)
                or d.get("huella_transaccion") != _hash({k: v for k, v in d.items() if k != "huella_transaccion"})):
            raise ValueError("Diario de recuperación inválido, alterado o de otra ubicación")
        nuevo = _selector(d.get("nuevo"))
        anterior = d.get("anterior")
        if fija:
            if huella is not None and huella != nuevo["huella_paquete"]:
                raise ValueError("Usa el administrador del slot candidato para recuperar esta operación")
            return nuevo, d.get("migracion_navegacion") is True
        if "migracion_navegacion" in d:
            if (d["migracion_navegacion"] is not True or d["accion"] != "actualizar"
                    or anterior is None or _selector(anterior) == nuevo):
                raise ValueError("Diario de migración de navegación inválido")
            if huella is not None and huella != nuevo["huella_paquete"]:
                raise ValueError("Usa la entrada de administración del slot candidato para recuperar la migración")
            return nuevo, True
        if anterior is not None:
            return _selector(anterior), False
        if d["accion"] != "instalar":
            raise ValueError("La actualización no conserva versión anterior para recuperar")
        return nuevo, False

    try:
        activo = _leer(raiz, base + "/activo.json")
    except FileNotFoundError:
        if huella is None:
            raise
        # Tras revertir una primera instalación, su entrada de respaldo puede
        # volver a informar el estado sin selector ni configuración del proyecto.
        return _selector_de_respaldo(raiz, base, huella), False
    return _selector(_json(activo[1].decode("utf-8"))), False


def _administrar(argv):
    import importlib
    import importlib.util

    raiz, base, entrada, huella = _ubicacion()
    argumentos = _argumentos(raiz, argv)
    selector, migracion = _seleccion_admin(raiz, base, huella)
    slot = _slot(raiz, base, selector, requiere_navegacion=migracion)
    capacidad_activa = (slot.relative_to(raiz) / _CAPACIDAD).as_posix()
    if _leer(raiz, entrada) != _leer(raiz, capacidad_activa):
        raise ValueError("La entrada de administración fue modificada")

    paquete = slot / "contenido/gobernanza"
    spec = importlib.util.spec_from_file_location(
        "gobernanza", paquete / "__init__.py", submodule_search_locations=[str(paquete)])
    if spec is None or spec.loader is None:
        raise ValueError("No se pudo cargar la versión íntegra de administración")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["gobernanza"] = modulo
    spec.loader.exec_module(modulo)
    return importlib.import_module("gobernanza.distribucion.cli").main(
        argumentos, base_instalacion=base)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    try:
        raise SystemExit(_administrar(sys.argv[1:]))
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        print("Kit local: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
