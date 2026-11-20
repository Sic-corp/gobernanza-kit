#!/usr/bin/env python3
"""Entrada autónoma que el kit instala como ./gobernanza-kit en cada checkout."""

import argparse
from http.client import HTTPException
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib import request
from urllib.parse import urlsplit


_RELEASES = "https://github.com/Sic-corp/gobernanza-kit/releases"
_CDN = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
        "github-releases.githubusercontent.com"}
_VERSION = r"V[0-9]+\.[0-9]{2}"
_CABECERA = re.compile(rb"\A#!/bin/sh\nversion='(V[0-9]+\.[0-9]{2})'\nsha256='[0-9a-f]{64}'\n")
_LIMITE = 256 * 1024


def _version(valor):
    if re.fullmatch(_VERSION, valor) is None:
        raise argparse.ArgumentTypeError("La versión debe tener el formato V3.02.")
    return valor


def _bootstrap(version):
    referencia = "download/" + version if version else "latest/download"
    url = f"{_RELEASES}/{referencia}/instalar.sh"
    with request.urlopen(url, timeout=30) as respuesta:
        destino = urlsplit(respuesta.geturl())
        if destino.scheme != "https" or destino.hostname not in _CDN:
            raise ValueError("La descarga del instalador debe proceder de GitHub por HTTPS.")
        codigo = respuesta.read(_LIMITE + 1)
    cabecera = _CABECERA.match(codigo)
    if len(codigo) > _LIMITE or cabecera is None:
        raise ValueError("La descarga no contiene una cabecera válida de instalador.")
    if version and cabecera[1].decode("ascii") != version:
        raise ValueError(f"El instalador descargado no corresponde a {version}.")
    return codigo


def main(argv=None):
    cli = argparse.ArgumentParser(prog="./gobernanza-kit", description="Administra la versión de este proyecto.",
                                  allow_abbrev=False)
    verbos = cli.add_subparsers(dest="verbo", required=True)
    actualizar = verbos.add_parser("actualizar", help="Actualizar este proyecto desde una GitHub Release.",
                                   allow_abbrev=False)
    actualizar.add_argument("--version", type=_version, help="Etiqueta exacta de la release, por ejemplo V3.02.")
    actualizar.add_argument("--modo", choices=("estandar", "aislado", "ubicable"))
    actualizar.add_argument("--solo-plan", action="store_true", help="Mostrar los cambios previstos.")
    actualizar.add_argument("--activar-hook-solucion", action="store_true")
    argumentos = cli.parse_args(argv)
    raiz = Path(__file__).resolve().parent
    opciones = ["actualizar", "--raiz", str(raiz)]
    if argumentos.modo:
        opciones += ["--modo", argumentos.modo]
    if argumentos.solo_plan:
        opciones.append("--solo-plan")
    if argumentos.activar_hook_solucion:
        opciones.append("--activar-hook-solucion")
    try:
        codigo = _bootstrap(argumentos.version)
        with TemporaryDirectory(prefix="gobernanza-kit-") as carpeta:
            bootstrap = Path(carpeta) / "instalar.sh"
            bootstrap.write_bytes(codigo)
            salida = subprocess.run(["sh", str(bootstrap), *opciones], cwd=raiz, check=False).returncode
            return 128 - salida if salida < 0 else salida
    except (OSError, ValueError, HTTPException) as error:
        print(f"Gobernanza: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
