"""Servidor HTTP de lectura, limitado a la interfaz local."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
from urllib.parse import parse_qs, urlsplit

from .captura import Capturas
from .vista import CSS, HTML, JS


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True


class _Peticion(BaseHTTPRequestHandler):
    def _respuesta(self, codigo, cuerpo=b"", tipo="application/json; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        if cuerpo:
            self.wfile.write(cuerpo)

    def _json(self, codigo, contenido):
        self._respuesta(codigo, json.dumps(contenido, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host") != [host]:
            self._json(403, {"error": "La petición debe estar dirigida al servidor local."})
            return
        try:
            solicitud = urlsplit(self.path)
            parametros = parse_qs(solicitud.query, max_num_fields=4)
        except ValueError:
            self._json(400, {"error": "Petición inválida."})
            return
        if solicitud.scheme or solicitud.netloc:
            self._json(400, {"error": "Petición inválida."})
            return
        if solicitud.path in _RECURSOS:
            cuerpo, tipo = _RECURSOS[solicitud.path]
            self._respuesta(200, cuerpo, tipo)
            return
        if solicitud.path not in {"/api/captura", "/api/ruta"}:
            self._json(404, {"error": "Recurso desconocido."})
            return
        try:
            captura = self.server.capturas.actual()
            if solicitud.path == "/api/captura":
                if parametros.get("desde") == [captura["commit"]]:
                    self._respuesta(204)
                else:
                    self._json(200, captura)
            elif parametros.get("commit") != [captura["commit"]]:
                self._json(409, {"error": "Cambió el commit. Vuelve a consultar la captura."})
            else:
                destino = parametros.get("destino", [None])[0]
                self._json(200, self.server.capturas.ruta(destino, captura=captura))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            self._json(503, {"error": str(exc)})


_RECURSOS = {
    "/": (HTML.encode("utf-8"), "text/html; charset=utf-8"),
    "/tablero.css": (CSS.encode("utf-8"), "text/css; charset=utf-8"),
    "/tablero.js": (JS.encode("utf-8"), "text/javascript; charset=utf-8"),
}


def crear_servidor(raiz, puerto):
    capturas = Capturas(raiz)
    servidor = _Servidor(("127.0.0.1", puerto), _Peticion)
    servidor.capturas = capturas
    return servidor
