"""Inventario, traslado reversible y purga de slots propios de una sustitución."""

import os
from pathlib import PurePosixPath
import re

from ..nucleo.arboles import ErrorArbol, _git
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import _padre
from .paquete import REQUERIDOS, _recorrer, _ruta_archivo


_HUELLA = re.compile(r"[a-f0-9]{64}")
_MANIFIESTO = "manifiesto.json"


def _selectores_locales(raiz, ubicacion):
    from .gestor import ErrorGestor, _bytes, _leer_json, _segura, _selector_valido, _validar_diario

    activo = _leer_json(raiz, ubicacion.activo)
    if activo is not None:
        yield _selector_valido(activo)
    transacciones = _segura(raiz, ubicacion.transacciones)
    if not transacciones.exists():
        return
    for nombre in sorted(os.listdir(transacciones)):
        if not re.fullmatch(r"[a-f0-9]{32}", nombre):
            continue
        for archivo, resultados in (("registro.json", ("aplicada", "revertida")), ("recuperacion.json", ("recuperada",))):
            ruta = f"{ubicacion.transacciones}/{nombre}/{archivo}"
            registro = _leer_json(raiz, ruta)
            if registro is None:
                continue
            _validar_diario(registro, ubicacion)
            if registro["id"] != nombre or registro.get("resultado") not in resultados:
                raise ErrorGestor(f"El registro no corresponde a la transacción local: {ruta}")
            for lado in ("anterior", "nuevo"):
                imagen = registro["rutas"][ubicacion.activo][lado]
                selector = None if imagen is None else json_estricto(_bytes(imagen).decode("utf-8"))
                if selector != registro[lado]:
                    raise ErrorGestor(f"El selector no coincide con su respaldo en {ruta}.")
                if selector is not None:
                    yield selector


def _blob_regular(raiz, commit, ruta):
    entrada = _git(raiz, "ls-tree", "--full-tree", "-z", commit, "--", ruta)
    if entrada.startswith(b"100644 blob ") and entrada.split(b"\t", 1)[1] == ruta.encode("utf-8") + b"\0":
        return _git(raiz, "cat-file", "blob", commit + ":" + ruta)
    return None


def _selectores_historicos(raiz, ubicacion, pendientes):
    from .gestor import _selector, _selector_valido

    try:
        cabeza = _git(raiz, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    except ErrorArbol:
        # Una instalación local puede preceder al primer commit del consumidor.
        return
    commits = _git(raiz, "log", "--first-parent", "--format=%H", cabeza, "--", ubicacion.activo)
    for commit in commits.decode("ascii").splitlines():
        bruto = _blob_regular(raiz, commit, ubicacion.activo)
        if bruto is None:
            continue
        try:
            selector = _selector_valido(json_estricto(bruto.decode("utf-8")))
        except ValueError:
            continue
        huella = selector["huella_paquete"]
        if huella not in pendientes:
            continue
        ruta = ubicacion.version(selector) + "/" + _MANIFIESTO
        bruto = _blob_regular(raiz, commit, ruta)
        try:
            if bruto is not None and _selector(json_estricto(bruto.decode("utf-8"))) == selector:
                yield selector
        except (ValueError, TypeError, KeyError):
            # El historial previo al kit puede reutilizar nombres sin su formato.
            continue


def inventariar(raiz, ubicacion, conservar):
    from .gestor import ErrorGestor, _capturar, _firma, _leer_json, _segura, _selector, _validar_paquete

    versiones = _segura(raiz, ubicacion.base + "/versiones")
    if not versiones.exists():
        return {}
    nombres = {nombre for nombre in os.listdir(versiones) if _HUELLA.fullmatch(nombre) and nombre != conservar}
    if not nombres:
        return {}
    selectores = {s["huella_paquete"]: s for s in _selectores_locales(raiz, ubicacion)}
    pendientes = nombres - selectores.keys()
    if pendientes:
        selectores.update((s["huella_paquete"], s) for s in _selectores_historicos(raiz, ubicacion, pendientes))
    retirados = {}
    for huella in sorted(nombres & selectores.keys()):
        relativa = ubicacion.version(selectores[huella])
        carpeta = _segura(raiz, relativa)
        if not carpeta.is_dir():
            raise ErrorGestor(f"Slot anterior sin procedencia verificable: {relativa}")
        bruto = _leer_json(raiz, relativa + "/" + _MANIFIESTO)
        if not isinstance(bruto, dict) or not isinstance(bruto.get("archivos"), dict):
            raise ErrorGestor(f"Slot anterior sin inventario verificable: {relativa}")
        archivos, _ = _recorrer(carpeta)
        terceros = archivos - bruto["archivos"].keys() - {_MANIFIESTO}
        if terceros:
            raise ErrorGestor(f"Archivos ajenos en {relativa}: {', '.join(sorted(terceros))}")
        manifiesto = _validar_paquete(carpeta)
        if _selector(manifiesto) != selectores[huella]:
            raise ErrorGestor(f"El nombre del slot no coincide con su identidad: {relativa}")
        firmas = {ruta: _firma(_capturar(raiz, relativa + "/" + ruta)) for ruta in sorted(archivos)}
        if any(not firmas[ruta] or any(firmas[ruta][k] != meta[k] for k in ("modo", "sha256"))
               for ruta, meta in manifiesto["archivos"].items()):
            raise ErrorGestor(f"El slot cambió durante el inventario: {relativa}")
        retirados[huella] = firmas
    validar_inventario(retirados, conservar)
    return retirados


def validar_inventario(retirados, conservar):
    from .gestor import ErrorGestor

    if not isinstance(retirados, dict):
        raise ErrorGestor("El inventario de sustitución debe ser un objeto.")
    for huella, archivos in retirados.items():
        if (not isinstance(huella, str) or _HUELLA.fullmatch(huella) is None or huella == conservar
                or not isinstance(archivos, dict) or not (REQUERIDOS | {_MANIFIESTO}) <= archivos.keys()):
            raise ErrorGestor("El inventario de sustitución contiene un slot ajeno o incompleto.")
        for ruta, firma in archivos.items():
            if ruta != _MANIFIESTO:
                _ruta_archivo(ruta)
            if (not isinstance(firma, dict) or set(firma) != {"sha256", "modo", "permisos"}
                    or not isinstance(firma["sha256"], str) or _HUELLA.fullmatch(firma["sha256"]) is None
                    or type(firma["permisos"]) is not int or not 0 <= firma["permisos"] <= 0o777
                    or firma["modo"] != ("100755" if firma["permisos"] & 0o111 else "100644")):
                raise ErrorGestor(f"Metadatos de sustitución inválidos: {ruta}.")


def _cotejar(raiz, relativa, firmas, *, parcial=False):
    from .gestor import ErrorGestor, _capturar, _firma, _segura

    carpeta = _segura(raiz, relativa)
    if parcial and not carpeta.exists():
        return set(), set()
    if not carpeta.is_dir():
        raise ErrorGestor(f"Falta un directorio de sustitución: {relativa}.")
    archivos, directorios = _recorrer(carpeta)
    previstos = {p.as_posix() for ruta in firmas for p in PurePosixPath(ruta).parents if p.parts}
    terceros = (archivos - firmas.keys()) | (directorios - previstos)
    if terceros:
        raise ErrorGestor(f"Contenido ajeno preservado en {relativa}: {', '.join(sorted(terceros))}")
    if not parcial and archivos != firmas.keys():
        raise ErrorGestor(f"El slot de sustitución está incompleto: {relativa}.")
    for ruta in sorted(archivos):
        completa = relativa + "/" + ruta
        if _firma(_capturar(raiz, completa)) != firmas[ruta]:
            raise ErrorGestor(f"Imagen ajena preservada en {completa}.")
    return archivos, directorios


def _mover(raiz, origen, destino):
    from .gestor import ErrorGestor, _segura

    _segura(raiz, origen)
    _segura(raiz, destino)
    with _padre(raiz, origen) as (fd_origen, nombre_origen), _padre(raiz, destino, crear=True) as (fd_destino, nombre_destino):
        try:
            os.stat(nombre_destino, dir_fd=fd_destino, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ErrorGestor(f"Destino de sustitución ocupado: {destino}.")
        os.rename(nombre_origen, nombre_destino, src_dir_fd=fd_origen, dst_dir_fd=fd_destino)
        os.fsync(fd_origen)
        os.fsync(fd_destino)


def _carpeta_retiro(raiz, base, transaccion, retirados):
    from .gestor import ErrorGestor, _segura

    relativa = f"{base}/.sustitucion-{transaccion}"
    carpeta = _segura(raiz, relativa)
    if carpeta.exists():
        if not carpeta.is_dir():
            raise ErrorGestor(f"El retiro contiene un objeto ajeno: {relativa}.")
        terceros = set(os.listdir(carpeta)) - retirados.keys()
        if terceros:
            raise ErrorGestor(f"Contenido ajeno preservado en {relativa}: {', '.join(sorted(terceros))}")
    return relativa


def _rmdir(raiz, relativa):
    from .gestor import _segura

    if _segura(raiz, relativa).exists():
        with _padre(raiz, relativa) as (padre, nombre):
            os.rmdir(nombre, dir_fd=padre)
            os.fsync(padre)


def apartar(raiz, base, transaccion, retirados):
    ruta_retiro = _carpeta_retiro(raiz, base, transaccion, retirados)
    for huella, firmas in retirados.items():
        origen = f"{base}/versiones/{huella}"
        destino = f"{ruta_retiro}/{huella}"
        _cotejar(raiz, origen, firmas)
        _mover(raiz, origen, destino)
        _cotejar(raiz, destino, firmas)


def restaurar(raiz, base, transaccion, retirados):
    from .gestor import ErrorGestor, _segura

    ruta_retiro = _carpeta_retiro(raiz, base, transaccion, retirados)
    pendientes = []
    for huella, firmas in retirados.items():
        original = f"{base}/versiones/{huella}"
        apartada = f"{ruta_retiro}/{huella}"
        if _segura(raiz, apartada).exists():
            if _segura(raiz, original).exists():
                raise ErrorGestor(f"El slot original está ocupado: {original}.")
            _cotejar(raiz, apartada, firmas)
            pendientes.append((apartada, original))
        else:
            _cotejar(raiz, original, firmas)
    for origen, destino in pendientes:
        _mover(raiz, origen, destino)
    _rmdir(raiz, ruta_retiro)


def purgar(raiz, base, transaccion, retirados):
    from .gestor import ErrorGestor, _capturar, _eliminar, _firma, _segura

    ruta_retiro = _carpeta_retiro(raiz, base, transaccion, retirados)
    pendientes = []
    for huella, firmas in retirados.items():
        if _segura(raiz, f"{base}/versiones/{huella}").exists():
            raise ErrorGestor(f"Se preserva el slot reaparecido en versiones/{huella}.")
        relativa = f"{ruta_retiro}/{huella}"
        archivos, directorios = _cotejar(raiz, relativa, firmas, parcial=True)
        pendientes.append((relativa, firmas, archivos, directorios))
    for relativa, firmas, archivos, directorios in pendientes:
        for ruta in sorted(archivos):
            completa = relativa + "/" + ruta
            if _firma(_capturar(raiz, completa)) != firmas[ruta]:
                raise ErrorGestor(f"Imagen ajena preservada en {completa}.")
            _eliminar(raiz, completa)
        for ruta in sorted(directorios, key=lambda ruta: (ruta.count("/"), ruta), reverse=True):
            _rmdir(raiz, relativa + "/" + ruta)
        _rmdir(raiz, relativa)
    _rmdir(raiz, ruta_retiro)
