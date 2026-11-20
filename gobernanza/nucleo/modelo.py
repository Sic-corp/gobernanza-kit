"""Datos y resultados compartidos por F-0101 y F-0102; sin efectos de escritura."""

from dataclasses import dataclass
import fnmatch
import json
import re


def diagnostico(codigo, ruta, requisito, mensaje, resolucion):
    return dict(codigo=codigo, ruta=str(ruta) or ".", requisito=requisito,
                mensaje=mensaje, resolucion=resolucion)


def unicos(elementos):
    vistos = set()
    salida = []
    for elemento in elementos:
        clave = json.dumps(elemento, sort_keys=True, ensure_ascii=False)
        if clave not in vistos:
            vistos.add(clave)
            salida.append(elemento)
    return salida


def resultado(operacion, errores=(), pendientes=(), codigo=None):
    errores = unicos(errores)
    codigo = (1 if errores else 0) if codigo is None else codigo
    return {
        "operacion": operacion,
        "estado": "invalido" if codigo else "valido",
        "codigo": codigo,
        "resumen": "Diagnóstico estructural; no acredita entrega ni ejecución de pruebas.",
        "errores": errores,
        "pendientes": unicos(pendientes),
        "contratos": [],
        "criterios": [],
        "pruebas_declaradas": [],
        "referencias_externas": [],
        "limites": {
            "autoridad": False,
            "pruebas_ejecutadas": False,
            "descubrimiento_runner": False,
            "entrega_aceptada": False,
        },
    }


def referencia(texto):
    """Devuelve identidad y revisión explícita; no interpreta nombres de ramas."""
    if not isinstance(texto, str):
        return None
    patron = r"(F-\d{4})(?:@r([1-9]\d*))?|(M-[A-Za-z0-9_-]+)(?:@v([1-9]\d*))?|([SG]\d{2}-\d{2})"
    match = re.fullmatch(patron, texto)
    if match is None:
        return None
    funcionalidad, revision, modulo, version, sesion = match.groups()
    return (funcionalidad or modulo or sesion, int(revision or version) if revision or version else None)


def coincide(ruta, patron):
    """Glob por componentes, con ** y directorios; * nunca cruza una barra."""
    if patron.endswith("/"):
        return ruta == patron.rstrip("/") or ruta.startswith(patron)
    partes, patrones = ruta.split("/"), patron.split("/")

    def recorrer(i, j):
        if j == len(patrones):
            return i == len(partes)
        if patrones[j] == "**":
            return any(recorrer(k, j + 1) for k in range(i, len(partes) + 1))
        return i < len(partes) and fnmatch.fnmatchcase(partes[i], patrones[j]) and recorrer(i + 1, j + 1)

    return recorrer(0, 0)


@dataclass
class Documento:
    ruta: str
    datos: dict
    prosa: str

    @property
    def id(self):
        return self.datos["id"]

    @property
    def tipo(self):
        return "funcionalidad" if self.id.startswith("F-") else "modulo" if self.id.startswith("M-") else "sesion"

    def ref(self, revision=None):
        if self.tipo == "funcionalidad":
            return f"{self.id}@r{revision or self.datos['revision_actual']}"
        if self.tipo == "modulo":
            return f"{self.id}@v{self.datos['version']}"
        return self.id

    def contrato(self, revision=None, razones=()):
        return dict(id=self.id, referencia=self.ref(revision), tipo=self.tipo,
                    ruta=self.ruta, estado=self.datos.get("estado", "declarado"), razones=list(razones))

    def criterios(self, revision=None):
        if self.tipo != "funcionalidad":
            return []
        revision = revision or self.datos["revision_actual"]
        return [dict(referencia=f"{self.id}@r{revision}/{identificador}", ruta=self.ruta)
                for identificador in self.datos["criterios"].get(str(revision), [])]
