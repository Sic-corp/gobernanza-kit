"""Proyección del registro y hoja de ruta desde un único commit guardado."""

import io
import os
import re
import subprocess
from pathlib import PurePosixPath
from threading import Lock

from gobernanza.nucleo.arboles import ErrorArbol, LectorArbol, _raiz_repositorio, commit_lectura
from gobernanza.nucleo.documentos import json_estricto
from gobernanza.nucleo.modelo_sdd import _campos, leer, seccion


REGISTRO = "sdd/registro/"
HOJA = "sdd/ruta-de-desarrollo.md"
CONFIG = "gobernanza/config.json"


def _lote(lector, rutas):
    """Pide blobs regulares ya identificados por el inventario anclado."""
    esperados = {}
    for ruta in rutas:
        modo, oid = lector.entradas[lector.comprobar_ruta(ruta)]
        if modo not in {"100644", "100755"} or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise ErrorArbol(f"Archivo Git no regular: {ruta}.")
        esperados[ruta] = oid
    if not esperados:
        return {}
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    entorno.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    proceso = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "cat-file", "--batch"], cwd=lector.raiz,
        env=entorno, input=("\n".join(esperados.values()) + "\n").encode("ascii"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
    )
    if proceso.returncode:
        raise ErrorArbol("No se pudieron leer los blobs de la captura Git.")
    salida = {}
    datos = io.BytesIO(proceso.stdout)
    for ruta, oid in esperados.items():
        cabecera = datos.readline().split()
        if len(cabecera) != 3 or cabecera[:2] != [oid.encode("ascii"), b"blob"] or not cabecera[2].isdigit():
            raise ErrorArbol(f"Blob no disponible en el árbol: {ruta}.")
        longitud = int(cabecera[2])
        contenido = datos.read(longitud)
        if len(contenido) != longitud or datos.read(1) != b"\n":
            raise ErrorArbol(f"Blob incompleto: {ruta}.")
        salida[ruta] = contenido.decode("utf-8")
    return salida


def _parrafo(texto, seccion):
    patron = rf"^## {seccion}\s*\n\s*(.*?)(?=^## |^\| |\Z)"
    fragmento = re.search(patron, texto, re.M | re.S)
    return fragmento[1].strip() if fragmento else ""


def _titulo(datos, texto):
    if "titulo" in datos:
        return datos["titulo"]
    encabezado = re.search(r"^# +(.+)$", texto, re.M)
    if encabezado and " — " in encabezado[1]:
        return encabezado[1].split(" — ", 1)[1]
    return datos["ref"]


def _criterios(texto, ref):
    revision = ref.split("@", 1)[1]
    tramo = re.search(rf"^## {revision}\b[^\n]*\n(.*?)(?=^## |\Z)", texto, re.M | re.S)
    resultados = []
    for linea in (tramo[1] if tramo else texto).splitlines():
        resultado = (re.match(r"^\|\s*C[0-9]+\s*\|\s*(.+)\|\s*$", linea)
                     or re.match(r"^C[0-9]+\s*[.:·]\s*(.+)$", linea))
        if resultado:
            resultados.append(resultado[1].strip())
    return "\n".join(resultados)


def _ficha(documento, ruta):
    datos, texto = documento
    tipo = datos["tipo"]
    ficha = {"ref": datos["ref"], "title": _titulo(datos, texto), "estado": datos["estado"],
             "draft": datos["estado"] == "borrador", "path": ruta}
    if tipo == "spec":
        ficha["modules"] = datos.get("modulos", [])
    if tipo == "modulo":
        ficha["description"] = _parrafo(texto, "Descripción")
    if tipo == "funcionalidad":
        explicacion = _parrafo(texto, "Explicación")
        ficha.update(
            owner=datos.get("modulo"), citations=datos.get("secciones", []),
            dependencies=datos.get("dependencias", []),
            description=explicacion or _criterios(texto, datos["ref"]),
            historical=not bool(explicacion),
        )
    return ficha


def _ultimas(fichas, specs=None):
    revisiones = {}
    titulos = {}
    for ficha in fichas:
        identidad, version = ficha["ref"].split("@", 1)
        numero = int(version[1:])
        if identidad not in revisiones or numero > revisiones[identidad][0]:
            revisiones[identidad] = numero, ficha
        if ficha["title"] != ficha["ref"] and (identidad not in titulos or numero > titulos[identidad][0]):
            titulos[identidad] = numero, ficha["title"]
    salida = {}
    for identidad, (_, ficha) in sorted(revisiones.items()):
        if ficha["title"] == ficha["ref"]:
            titulo = titulos.get(identidad, (0, ""))[1] or _titulo_citado(ficha, specs)
            if titulo:
                ficha = {**ficha, "title": titulo}
        salida[identidad] = ficha
    return salida


def _titulo_citado(ficha, specs):
    if specs is None:
        return ""
    for referencia in ficha.get("citations", []):
        try:
            texto = seccion(specs, referencia)
        except ValueError:
            continue
        encabezado = re.search(r"^## +(.+)$", texto, re.M)
        if encabezado:
            titulo = encabezado[1]
            if " " in titulo and not titulo.isupper():
                return titulo
    return ""


def _sesiones(registros, fichas):
    enlaces = {}
    for datos, texto in registros:
        destinos = datos.get("destinos_ruta", [])
        if not destinos:
            continue
        referencias = datos.get("funcionalidades", [])
        sesion = {
            "ref": datos["ref"], "titulo": _titulo(datos, texto), "fase": datos["estado"],
            "funcionalidades": referencias,
            "secciones": sorted({cita for ref in referencias for cita in fichas.get(ref, {}).get("citations", [])}),
            "evidencias": datos.get("evidencias", []),
        }
        for destino in set(destinos):
            enlaces.setdefault(destino, []).append(sesion)
    return enlaces


def _hoja(lector, registros, fichas):
    try:
        hojas = _lote(lector, [HOJA] if HOJA in lector.rutas else [])
        if HOJA not in hojas:
            raise ValueError("Falta la hoja de ruta guardada en el repositorio.")
        from gobernanza.nucleo.ruta_desarrollo import leer_ruta, proyeccion_ruta
        metas = leer_ruta(hojas[HOJA])
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"path": HOJA, "error": str(exc), "metas": [], "siguiente": None}
    enlaces = _sesiones(registros, fichas)
    for meta in metas:
        for hito in [meta, *meta["objetivos"]]:
            hito["sesiones"] = enlaces.get(hito["id"], [])
    return {"path": HOJA, "error": None, **proyeccion_ruta(metas)}


def _captura(raiz, commit):
    lector = LectorArbol(raiz, commit)
    rutas = [ruta for ruta in lector.listar(REGISTRO) if PurePosixPath(ruta).parent.as_posix() == REGISTRO.rstrip("/")
             and ruta.endswith(".md")]
    archivos = _lote(lector, [CONFIG, *rutas] if CONFIG in lector.rutas else rutas)
    config = json_estricto(archivos.pop(CONFIG, "{}"))
    proyecto = config.get("proyecto") if isinstance(config, dict) else None
    fichas = {"spec": [], "modulo": [], "funcionalidad": []}
    sesiones = []
    documentos_spec = {}
    for ruta, contenido in archivos.items():
        documento = leer(contenido)
        datos = documento[0]
        errores = _campos(PurePosixPath(ruta).stem, documento)
        if errores:
            raise ValueError(f"Ficha documental inválida: {ruta}.")
        if datos["tipo"] == "sesion":
            sesiones.append(documento)
        elif datos["tipo"] in fichas:
            fichas[datos["tipo"]].append(_ficha(documento, ruta))
            if datos["tipo"] == "spec":
                documentos_spec[datos["ref"]] = documento
    por_ref = {ficha["ref"]: ficha for ficha in fichas["funcionalidad"]}
    return {
        "project": proyecto if isinstance(proyecto, str) and proyecto else lector.raiz.name,
        "commit": lector.commit,
        "specs": _ultimas(fichas["spec"]),
        "modules": {ficha["ref"]: ficha for ficha in fichas["modulo"]},
        "functions": _ultimas(fichas["funcionalidad"], documentos_spec),
        "ruta": _hoja(lector, sesiones, por_ref),
    }


class Capturas:
    """Una sola captura en memoria, reemplazada después de leer el nuevo HEAD."""

    def __init__(self, raiz):
        self.raiz = _raiz_repositorio(raiz)
        self._lock = Lock()
        self._vigente = None

    def actual(self):
        with self._lock:
            commit = commit_lectura(self.raiz, "HEAD")
            if self._vigente is None or self._vigente["commit"] != commit:
                self._vigente = _captura(self.raiz, commit)
            return self._vigente

    def ruta(self, destino=None, *, captura=None):
        captura = captura if captura is not None else self.actual()
        hoja = captura["ruta"]
        if hoja["error"]:
            return {"commit": captura["commit"], **hoja}
        from gobernanza.nucleo.ruta_desarrollo import proyeccion_ruta
        return {"commit": captura["commit"], **hoja, **proyeccion_ruta(hoja["metas"], destino)}
