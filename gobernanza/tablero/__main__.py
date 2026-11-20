"""Abre el tablero del repositorio seleccionado en el navegador."""

import argparse
import subprocess
import sys
import webbrowser

from .servidor import crear_servidor


def _abrir(url):
    if sys.platform == "darwin":
        try:
            salida = subprocess.run(["/usr/bin/open", "-a", "Safari", url],
                                    capture_output=True, check=False, timeout=10)
            if salida.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    webbrowser.open(url)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Consulta el catálogo SDD y la ruta de desarrollo local.")
    parser.add_argument("--raiz", default=".", help="Raíz exacta del repositorio Git.")
    parser.add_argument("--puerto", type=int, default=0, help="Puerto local. 0 elige uno disponible.")
    parser.add_argument("--sin-abrir", action="store_true", help="Muestra la URL sin abrir el navegador.")
    args = parser.parse_args(argv)
    if not 0 <= args.puerto <= 65535:
        parser.error("El puerto debe estar entre 0 y 65535.")
    try:
        with crear_servidor(args.raiz, args.puerto) as servidor:
            url = f"http://127.0.0.1:{servidor.server_port}/"
            print(url, flush=True)
            if not args.sin_abrir:
                _abrir(url)
            servidor.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as exc:
        print(f"No se pudo abrir el tablero. {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
