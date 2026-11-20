#!/bin/sh
version='@VERSION_PUBLICA@'
sha256='@SHA256_ZIP@'
set -eu
exec python3 -I - "$version" "$sha256" "$@" <<'PYTHON'
import argparse
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import re
from shutil import copyfileobj
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from unicodedata import normalize
from urllib import request
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
import zlib


RELEASES = "https://github.com/Sic-corp/gobernanza-kit/releases/download"
RUTA_RELEASES = "/Sic-corp/gobernanza-kit/releases/download/"
CDN = {"release-assets.githubusercontent.com", "objects.githubusercontent.com",
       "github-releases.githubusercontent.com"}
VERSION = r"V[0-9]+\.[0-9]{2}"
ACTIVO_RELEASE = re.compile(re.escape(RUTA_RELEASES) + VERSION + rf"/(?:instalar\.sh|Gobernanza-Kit-{VERSION}\.zip)")
SHA256 = r"[0-9a-f]{64}"
CABECERA = re.compile(rb"\A#!/bin/sh\nversion='(" + VERSION.encode() +
                      rb")'\nsha256='(" + SHA256.encode() + rb")'\n")
MAX_BOOTSTRAP = 256 * 1024
MAX_ZIP = 256 * 1024 * 1024
MAX_EXTRAIDO = 512 * 1024 * 1024
MAX_ENTRADAS = 20_000


def opciones(argv):
    p = argparse.ArgumentParser(description="Instalar o actualizar una release pública del Kit de Gobernanza.")
    p.add_argument("--raiz", type=Path, default=Path.cwd(), help="Checkout del consumidor (directorio actual por defecto)")
    p.add_argument("--version", help="Tag de release exacto, por ejemplo V3.02")
    p.add_argument("--json", action="store_true")
    verbos = p.add_subparsers(dest="accion", required=True)
    for accion in ("instalar", "actualizar"):
        sub = verbos.add_parser(accion)
        sub.add_argument("--raiz", type=Path, default=argparse.SUPPRESS)
        sub.add_argument("--version", default=argparse.SUPPRESS)
        sub.add_argument("--modo", choices=("estandar", "aislado", "ubicable"))
        sub.add_argument("--solo-plan", action="store_true", help="Muestra el plan sin aplicar cambios")
        sub.add_argument("--activar-hook-solucion", action="store_true")
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p.parse_args(argv)


def comprobar_url(url):
    destino = urlsplit(url)
    host = destino.hostname
    autorizado = (host == "github.com" and ACTIVO_RELEASE.fullmatch(destino.path)) or host in CDN
    if (destino.scheme != "https" or not autorizado or destino.username is not None
            or destino.password is not None or destino.port not in (None, 443) or destino.fragment):
        raise ValueError(f"Redirección HTTPS de descarga no autorizada ({host or 'sin host'}).")


class RedireccionGithub(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        comprobar_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def descargar(opener, url, archivo, limite):
    comprobar_url(url)
    consulta = request.Request(url, headers={"User-Agent": "gobernanza-kit", "Accept-Encoding": "identity"})
    huella = hashlib.sha256()
    leidos = 0
    with opener.open(consulta, timeout=30) as respuesta:
        comprobar_url(respuesta.geturl())
        if respuesta.status != 200:
            raise ValueError(f"Respuesta HTTP inesperada: {respuesta.status}.")
        longitud = respuesta.headers.get("Content-Length")
        if longitud is not None:
            if not re.fullmatch(r"[0-9]{1,12}", longitud) or int(longitud) > limite:
                raise ValueError("Longitud HTTP inválida o superior al límite de descarga.")
            longitud = int(longitud)
        while bloque := respuesta.read(1024 * 1024):
            leidos += len(bloque)
            if leidos > limite:
                raise ValueError("La descarga excede su límite de tamaño.")
            huella.update(bloque)
            archivo.write(bloque)
    if longitud is not None and leidos != longitud:
        raise ValueError("Descarga incompleta: los bytes no coinciden con la longitud HTTP.")
    return huella.hexdigest()


def elegir_version(opener, temporal, version, pin, elegida):
    if not re.fullmatch(VERSION, version) or not re.fullmatch(SHA256, pin):
        raise ValueError("El bootstrap requiere una versión y un SHA-256 publicados.")
    if elegida is None:
        return version, pin
    if not re.fullmatch(VERSION, elegida):
        raise ValueError(f"Tag de release inválido: {elegida!r}.")
    with (temporal / "cabecera").open("w+b") as archivo:
        descargar(opener, f"{RELEASES}/{elegida}/instalar.sh", archivo, MAX_BOOTSTRAP)
        archivo.seek(0)
        cabecera = CABECERA.match(archivo.read(512))
    if cabecera is None or cabecera[1].decode("ascii") != elegida:
        raise ValueError(f"El bootstrap descargado no identifica el tag solicitado {elegida}.")
    return elegida, cabecera[2].decode("ascii")


def inventario(zip):
    entradas = zip.infolist()
    if len(entradas) > MAX_ENTRADAS or sum(m.file_size for m in entradas) > MAX_EXTRAIDO:
        raise ValueError("El ZIP excede el límite de entradas o bytes extraídos.")
    rutas, portables = {}, {}
    for miembro in entradas:
        nombre = miembro.filename
        partes = tuple(nombre.removesuffix("/").split("/"))
        if (miembro.orig_filename != nombre or any(p in {"", ".", ".."} for p in partes)
                or any(c in nombre for c in ("\\", ":")) or any(ord(c) < 32 or ord(c) == 127 for c in nombre)):
            raise ValueError(f"Ruta ZIP insegura: {nombre!r}.")
        modo = miembro.external_attr >> 16
        modos = {stat.S_IFDIR | 0o700, stat.S_IFDIR | 0o755} if miembro.is_dir() else {
            stat.S_IFREG | 0o644, stat.S_IFREG | 0o755}
        if miembro.create_system != 3 or modo not in modos or miembro.flag_bits & 1:
            raise ValueError(f"Tipo, permisos o cifrado ZIP no admitidos: {nombre!r}.")
        if partes in rutas:
            raise ValueError(f"Entrada ZIP duplicada: {nombre!r}.")
        rutas[partes] = miembro
        for fin in range(1, len(partes) + 1):
            prefijo = partes[:fin]
            portable = normalize("NFC", "/".join(prefijo)).casefold()
            if portables.setdefault(portable, prefijo) != prefijo:
                raise ValueError(f"Rutas ZIP con alias: {nombre!r}.")
    for partes, miembro in rutas.items():
        for fin in range(1, len(partes)):
            padre = rutas.get(partes[:fin])
            if padre is not None and not padre.is_dir():
                raise ValueError(f"Archivo ZIP usado como directorio: {miembro.filename!r}.")
    for requerido in ("instalar.py", "entrega.json"):
        miembro = rutas.get((requerido,))
        if miembro is None or miembro.is_dir():
            raise ValueError(f"El ZIP carece del archivo de entrega {requerido}.")
    return rutas


def extraer(archivo, destino):
    with ZipFile(archivo) as zip:
        rutas = inventario(zip)
        destino.mkdir(mode=0o700)
        for partes, miembro in rutas.items():
            ruta = destino.joinpath(*partes)
            if miembro.is_dir():
                ruta.mkdir(parents=True, exist_ok=True)
            else:
                ruta.parent.mkdir(parents=True, exist_ok=True)
                with zip.open(miembro) as origen, ruta.open("xb") as salida:
                    copyfileobj(origen, salida)
                ruta.chmod(stat.S_IMODE(miembro.external_attr >> 16))


def ejecutar(args, version, huella):
    raiz = args.raiz.resolve(strict=True)
    if not raiz.is_dir():
        raise ValueError("La raíz del consumidor debe ser un directorio.")
    with TemporaryDirectory(prefix="gobernanza-release-") as temporal:
        temporal = Path(temporal)
        opener = request.build_opener(RedireccionGithub())
        version, huella = elegir_version(opener, temporal, version, huella, args.version)
        nombre = f"Gobernanza-Kit-{version}.zip"
        archivo = temporal / nombre
        with archivo.open("xb") as salida:
            observado = descargar(opener, f"{RELEASES}/{version}/{nombre}", salida, MAX_ZIP)
        if observado != huella:
            raise ValueError(f"SHA-256 distinto del ZIP publicado para {version}.")
        entrega = temporal / "entrega"
        extraer(archivo, entrega)
        argv = [sys.executable, "-I", str(entrega / "instalar.py"), "--raiz", str(raiz), args.accion]
        if args.modo:
            argv.extend(("--modo", args.modo))
        if args.solo_plan:
            argv.append("--solo-plan")
        if args.activar_hook_solucion:
            argv.append("--activar-hook-solucion")
        if args.json:
            argv.append("--json")
        codigo = subprocess.run(argv, check=False).returncode
        return 128 - codigo if codigo < 0 else codigo


args = opciones(sys.argv[3:])
try:
    sys.exit(ejecutar(args, sys.argv[1], sys.argv[2]))
except (OSError, ValueError, HTTPException, BadZipFile, zlib.error, RuntimeError) as exc:
    if args.json:
        print(json.dumps(dict(operacion="descarga", estado="invalido", codigo=1,
                              resumen="No se pudo verificar o abrir la entrega pública.",
                              errores=[dict(codigo="DESCARGA_INVALIDA", mensaje=str(exc))]), ensure_ascii=False))
    else:
        print(f"Descarga: {exc}", file=sys.stderr)
    sys.exit(1)
PYTHON
