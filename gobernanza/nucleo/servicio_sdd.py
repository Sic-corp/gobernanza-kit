"""Servicio local para aplicar operaciones SDD sin prestar permisos al cliente."""

import base64
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket as unix_socket
import stat
import struct
import sys
import tempfile

from .arboles import _leer_trabajo, _ruta, _validar_captura
from .documentos import json_estricto
from .inicio import _eliminar, _escribir_bytes, _padre


RAICES_SDD = ("sdd", "gobernanza/sdd")
_MAX_MENSAJE = 8 * 1024 * 1024
_MAX_DOCUMENTO = 2 * 1024 * 1024
_MAX_ARCHIVOS = 2048
_MAX_SDD_BYTES = 64 * 1024 * 1024
_PENDIENTE = "pendiente.json"
_VIGENTE = "vigente.json"
_TEMPORAL = re.compile(r"\.gobernanza-[0-9a-f]{32}\.tmp\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ConfiguracionSDD:
    raiz: Path
    estado: Path
    socket: Path
    uid_agente: int
    gid_agente: int
    base: str
    alcance: tuple[str, ...]
    referencia: Path | None = None


def _json(datos):
    return json.dumps(datos, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _sha(datos):
    return hashlib.sha256(datos).hexdigest()


def _error(exc):
    return {"codigo": 1, "resumen": str(exc)}


def _ruta_sdd(ruta):
    ruta = _ruta(ruta)
    if not any(ruta.startswith(raiz + "/") for raiz in RAICES_SDD):
        raise ValueError(f"Destino fuera de SDD: {ruta}")
    if _TEMPORAL.fullmatch(PurePosixPath(ruta).name):
        raise ValueError(f"Nombre reservado por el servicio: {ruta}")
    return ruta


def _inventariar(raiz):
    archivos = {}
    acumulado = 0
    for prefijo in RAICES_SDD:
        base = raiz / prefijo
        if not stat.S_ISDIR(base.lstat().st_mode):
            raise ValueError(f"La raíz protegida debe ser un directorio real: {prefijo}")
        for actual, directorios, nombres in os.walk(base, followlinks=False, onerror=_propagar):
            for directorio in directorios:
                if not stat.S_ISDIR((Path(actual) / directorio).lstat().st_mode):
                    raise ValueError(f"Directorio SDD enlazado: {Path(actual) / directorio}")
            for nombre in nombres:
                origen = Path(actual) / nombre
                ruta = _ruta_sdd(origen.relative_to(raiz).as_posix())
                datos = origen.lstat()
                if (not stat.S_ISREG(datos.st_mode) or datos.st_nlink != 1
                        or datos.st_size > _MAX_DOCUMENTO or len(archivos) >= _MAX_ARCHIVOS):
                    raise ValueError(f"Entrada SDD enlazada, especial o fuera de tamaño: {ruta}")
                archivo = _leer_trabajo(raiz, ruta)
                if archivo is None or archivo[0] == "120000":
                    raise ValueError(f"La entrada SDD cambió durante la captura: {ruta}")
                acumulado += len(archivo[1])
                if acumulado > _MAX_SDD_BYTES:
                    raise ValueError("El contenido SDD supera el tamaño total admitido.")
                archivos[ruta] = archivo
    _validar_captura(archivos)
    return archivos


def _propagar(exc):
    raise exc


def _manifest(archivos):
    return {ruta: {"modo": modo, "sha256": _sha(datos)} for ruta, (modo, datos) in sorted(archivos.items())}


def _sincronizar(raiz, ruta):
    with _padre(raiz, ruta) as (padre, _):
        os.fsync(padre)


def _escribir(raiz, ruta, datos, *, modo="100644"):
    _escribir_bytes(raiz, ruta, datos, modo=modo)
    _sincronizar(raiz, ruta)


def _quitar(raiz, ruta):
    _eliminar(raiz, ruta)
    try:
        _sincronizar(raiz, ruta)
    except FileNotFoundError:
        pass


def _leer_json(raiz, ruta):
    archivo = _leer_trabajo(raiz, ruta)
    if archivo is None:
        return None
    if archivo[0] != "100644":
        raise ValueError(f"Estado del servicio inesperado: {ruta}")
    datos = json_estricto(archivo[1].decode("utf-8"))
    if not isinstance(datos, dict):
        raise ValueError(f"Estado del servicio inválido: {ruta}")
    return datos


@contextmanager
def _bloqueo(raiz, nombre, *, no_bloqueante=False):
    with _padre(raiz, nombre) as (padre, archivo):
        descriptor = os.open(archivo, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=padre)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (fcntl.LOCK_NB if no_bloqueante else 0))
        yield
    finally:
        os.close(descriptor)


def _ancestros_confiables(ruta):
    for padre in ruta.parents:
        datos = padre.lstat()
        if (not stat.S_ISDIR(datos.st_mode) or datos.st_uid not in {0, os.geteuid()}
                or (datos.st_mode & 0o022 and not datos.st_mode & stat.S_ISVTX)):
            raise ValueError(f"Un ancestro permite reemplazar el estado del escritor: {padre}")


def _directorio_privado(ruta):
    estado = ruta.lstat()
    if (not stat.S_ISDIR(estado.st_mode) or estado.st_uid != os.geteuid()
            or estado.st_mode & 0o077):
        raise ValueError(f"El estado requiere un directorio privado del escritor: {ruta}")


def _directorio_socket(ruta, gid):
    estado = ruta.lstat()
    if (not stat.S_ISDIR(estado.st_mode) or estado.st_uid != os.geteuid()
            or estado.st_mode & 0o027 or (estado.st_mode & 0o070 and estado.st_gid != gid)):
        raise ValueError(f"El directorio del socket requiere dueño escritor y grupo de acceso: {ruta}")


class ServicioSDD:
    """Un servicio registra un solo worktree y una base previamente autorizada."""

    def __init__(self, config, planificar, *, comprobar_proteccion, imagen_base=None):
        self.config = config
        self.planificar = planificar
        self.comprobar_proteccion = comprobar_proteccion
        self.imagen_base = imagen_base
        self.uid_escritor = os.geteuid()
        for ruta in (config.raiz, config.estado, config.socket.parent, config.referencia):
            if ruta is not None and (not ruta.is_absolute() or ruta.resolve(strict=True) != ruta):
                raise ValueError(f"La configuración requiere rutas absolutas y canónicas: {ruta}")
        for ruta in (config.estado, config.socket, config.referencia):
            if ruta is not None and ruta.is_relative_to(config.raiz):
                raise ValueError("El estado, socket y referencia del servicio deben vivir fuera del checkout.")
        if (type(config.uid_agente) is not int or config.uid_agente <= 0 or config.uid_agente == self.uid_escritor
                or type(config.gid_agente) is not int or config.gid_agente <= 0):
            raise ValueError("El agente necesita una identidad distinta a la del escritor y sin privilegios.")
        if not isinstance(config.base, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", config.base):
            raise ValueError("La base registrada debe ser una referencia Git completa.")
        if not config.alcance:
            raise ValueError("El alcance documental registrado no puede estar vacío.")
        for alcance in config.alcance:
            candidato = alcance.removesuffix("/")
            if candidato not in RAICES_SDD or not alcance.endswith("/"):
                _ruta_sdd(candidato)
        for ruta in (config.estado, config.socket.parent, config.referencia):
            if ruta is not None:
                _ancestros_confiables(ruta)
        _directorio_privado(config.estado)
        _directorio_socket(config.socket.parent, config.gid_agente)
        if config.referencia is not None:
            _directorio_privado(config.referencia.parent)

    def procesar(self, solicitud, *, uid):
        try:
            if type(uid) is not int or uid not in {self.config.uid_agente, self.uid_escritor}:
                raise ValueError("La identidad local no está registrada para este servicio.")
            if not isinstance(solicitud, dict) or solicitud.get("raiz") != str(self.config.raiz):
                raise ValueError("La solicitud no corresponde al checkout registrado.")
            operacion = solicitud.get("operacion")
            if (operacion == "estado" and set(solicitud) != {"operacion", "raiz"}
                    or operacion == "registrar" and set(solicitud) != {"operacion", "raiz", "lote", "aplicar"}
                    or operacion not in ("estado", "registrar")):
                raise ValueError("Operación o campos del servicio inválidos.")
            with self._bloquear_vigente() as (archivos, actual):
                if operacion == "estado":
                    return self._respuesta(actual)
                return self._registrar(solicitud["lote"], solicitud["aplicar"], uid, archivos, actual)
        except (ValueError, KeyError, OSError, TypeError, RuntimeError) as exc:
            return _error(exc)

    @contextmanager
    def _bloquear_vigente(self):
        with _bloqueo(self.config.estado, "lotes.lock"):
            self.comprobar_proteccion(self.config.raiz, self.config.uid_agente)
            self._recuperar()
            archivos = _inventariar(self.config.raiz)
            yield archivos, self._vigente(archivos)

    def con_imagen_vigente(self, accion):
        """Ejecuta el control Git local mientras las escrituras SDD esperan."""
        with self._bloquear_vigente() as (_, actual):
            return accion(actual["archivos"])

    def _vigente(self, archivos):
        manifest = _manifest(archivos)
        actual = {"base": self.config.base, "generacion": _sha(_json(manifest)), "archivos": manifest,
                  "raiz": str(self.config.raiz)}
        registrado = _leer_json(self.config.estado, _VIGENTE)
        if registrado is None:
            if self.imagen_base is not None and manifest != self.imagen_base:
                raise ValueError("El estado SDD inicial difiere del árbol Git de confianza.")
            _escribir(self.config.estado, _VIGENTE, _json(actual))
        elif registrado != actual:
            raise ValueError("El contenido SDD del checkout difiere del estado autorizado por el servicio.")
        return actual

    def _respuesta(self, actual, *, cambios=(), recibo=None, idempotente=False):
        return {"codigo": 0, "resumen": "Estado de SDD comprobado.", "base": actual["base"],
                "generacion": actual["generacion"], "archivos": actual["archivos"],
                "cambios": list(cambios), "recibo": recibo, "idempotente": idempotente}

    def _plan(self, cambios, uid, archivos):
        autorizadas = set()

        def autorizar(ruta, accion, requiere_dueno):
            ruta = _ruta_sdd(ruta)
            if accion not in {"alta", "modificar", "indice"} or type(requiere_dueno) is not bool:
                raise ValueError(f"Operación de escritura inválida: {accion!r}")
            if requiere_dueno and uid != self.uid_escritor:
                raise ValueError(f"La operación requiere aprobación del dueño: {ruta}")
            if not any(ruta == alcance or (alcance.endswith("/") and ruta.startswith(alcance))
                       for alcance in self.config.alcance):
                raise ValueError(f"El destino está fuera del alcance registrado: {ruta}")
            autorizadas.add(ruta)

        with tempfile.TemporaryDirectory(prefix="vista-", dir=self.config.estado) as temporal:
            imagen = Path(temporal)
            for raiz in RAICES_SDD:
                (imagen / raiz).mkdir(parents=True, exist_ok=True)
            for ruta, (_, datos) in archivos.items():
                destino = imagen / ruta
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(datos)
            self._copiar_estados(imagen)
            salidas = self.planificar(imagen, cambios, autorizar=autorizar)
        if not isinstance(salidas, dict):
            raise ValueError("El plan documental debe devolver un mapa de rutas y bytes.")
        actualizadas = {}
        for ruta, datos in salidas.items():
            if ruta not in autorizadas or not isinstance(datos, bytes) or len(datos) > _MAX_DOCUMENTO:
                raise ValueError(f"Salida no autorizada o fuera de tamaño: {ruta}")
            modo = archivos.get(ruta, ("100644", None))[0]
            if archivos.get(ruta) != (modo, datos):
                actualizadas[ruta] = (modo, datos)
        candidato = archivos | actualizadas
        if len(candidato) > _MAX_ARCHIVOS or sum(len(datos) for _, datos in candidato.values()) > _MAX_SDD_BYTES:
            raise ValueError("Se superó el límite del inventario de SDD.")
        _validar_captura(candidato)
        return actualizadas

    def _copiar_estados(self, imagen):
        origen = self.config.referencia
        if origen is None:
            return
        for prefijo in ("sesiones/modulos", "gobernanza/sesiones/modulos"):
            for archivo in sorted((origen / prefijo).glob("*/estado.md")):
                ruta = archivo.relative_to(origen).as_posix()
                leido = _leer_trabajo(origen, ruta)
                if leido is None or leido[0] != "100644" or len(leido[1]) > _MAX_DOCUMENTO:
                    raise ValueError(f"Estado de referencia inválido: {ruta}")
                destino = imagen / ruta
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(leido[1])

    def _registrar(self, lote, aplicar, uid, archivos, actual):
        if (type(aplicar) is not bool or not isinstance(lote, dict)
                or set(lote) != {"base", "generacion", "cambios"} or not isinstance(lote["cambios"], list)
                or not lote["cambios"] or not all(isinstance(c, dict) for c in lote["cambios"])):
            raise ValueError("El lote requiere base, generación y una lista no vacía de cambios.")
        if lote["base"] != actual["base"]:
            raise ValueError("El lote usa otra base Git. Consulta el estado y genera otra vista previa.")
        identificador = _sha(_json({"lote": lote, "uid": uid, "raiz": actual["raiz"]}))
        ruta_recibo = f"recibo-{identificador}.json"
        if aplicar:
            anterior = _leer_json(self.config.estado, ruta_recibo)
            if anterior is not None:
                return self._respuesta(anterior, cambios=anterior["cambios"], recibo=anterior, idempotente=True)
        if lote["generacion"] != actual["generacion"]:
            raise ValueError("La generación SDD del lote quedó desactualizada. Consulta el estado.")
        actualizadas = self._plan(lote["cambios"], uid, archivos)
        if not aplicar:
            return self._respuesta(actual, cambios=sorted(actualizadas))
        manifest = _manifest(archivos | actualizadas)
        recibo = {"id": identificador, "uid": uid, "base": actual["base"], "raiz": actual["raiz"],
                  "generacion_anterior": actual["generacion"], "generacion": _sha(_json(manifest)),
                  "cambios": sorted(actualizadas), "archivos": manifest}
        self._publicar(archivos, actualizadas, recibo, ruta_recibo)
        return self._respuesta(recibo, cambios=recibo["cambios"], recibo=recibo)

    def _publicar(self, archivos, actualizadas, recibo, ruta_recibo):
        raiz, estado = self.config.raiz, self.config.estado
        directorios = {padre.as_posix() for ruta in actualizadas for padre in PurePosixPath(ruta).parents
                       if padre.parts and not (raiz / padre).exists()}
        iniciales = {}
        for ruta in actualizadas:
            previo = archivos.get(ruta)
            iniciales[ruta] = None if previo is None else [previo[0], base64.b64encode(previo[1]).decode("ascii")]
        diario = {"id": recibo["id"], "iniciales": iniciales, "directorios": sorted(directorios),
                  "generacion_anterior": recibo["generacion_anterior"]}
        _escribir(estado, _PENDIENTE, _json(diario))
        try:
            for ruta, (modo, datos) in sorted(actualizadas.items()):
                _escribir(raiz, ruta, datos, modo=modo)
            for ruta in sorted(directorios, key=lambda ruta: len(PurePosixPath(ruta).parts), reverse=True):
                _sincronizar(raiz, ruta)
            if _manifest(_inventariar(raiz)) != recibo["archivos"]:
                raise ValueError("El lote publicado no coincide con el candidato validado.")
            _escribir(estado, ruta_recibo, _json(recibo))
        finally:
            self._recuperar()

    def _recuperar(self):
        raiz, estado = self.config.raiz, self.config.estado
        diario = _leer_json(estado, _PENDIENTE)
        if diario is None:
            return
        identificador = diario["id"]
        if not isinstance(identificador, str) or not _DIGEST.fullmatch(identificador):
            raise ValueError("El identificador del diario del servicio es inválido.")
        recibo = _leer_json(estado, f"recibo-{identificador}.json")
        if recibo is not None:
            actual = {campo: recibo[campo] for campo in ("raiz", "base", "generacion", "archivos")}
            if _manifest(_inventariar(raiz)) != actual["archivos"]:
                raise ValueError("El lote confirmado no coincide con el estado SDD recuperado.")
            _escribir(estado, _VIGENTE, _json(actual))
        else:
            for ruta, imagen in sorted(diario["iniciales"].items()):
                _ruta_sdd(ruta)
                padre = (raiz / ruta).parent
                if padre.is_dir():
                    for temporal in padre.glob(".gobernanza-*.tmp"):
                        if _TEMPORAL.fullmatch(temporal.name):
                            _quitar(raiz, temporal.relative_to(raiz).as_posix())
                if imagen is None:
                    _quitar(raiz, ruta)
                else:
                    modo, contenido = imagen
                    _escribir(raiz, ruta, base64.b64decode(contenido, validate=True), modo=modo)
            for ruta in sorted(diario["directorios"], key=lambda ruta: len(PurePosixPath(ruta).parts), reverse=True):
                try:
                    with _padre(raiz, _ruta_sdd(ruta)) as (padre, nombre):
                        os.rmdir(nombre, dir_fd=padre)
                        os.fsync(padre)
                except FileNotFoundError:
                    pass
            if _sha(_json(_manifest(_inventariar(raiz)))) != diario["generacion_anterior"]:
                raise ValueError("La restauración del lote no recuperó el estado SDD anterior.")
        _quitar(estado, _PENDIENTE)

    def servir(self, *, detener=None):
        """Atiende un socket Unix con una petición JSON por conexión."""
        self.comprobar_proteccion(self.config.raiz, self.config.uid_agente)
        ruta = self.config.socket
        with _bloqueo(self.config.estado, "servicio.lock", no_bloqueante=True):
            _retirar_socket_huerfano(ruta)
            with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as servidor:
                servidor.bind(str(ruta))
                try:
                    os.chown(ruta, -1, self.config.gid_agente)
                    ruta.chmod(0o660)
                    servidor.listen(8)
                    servidor.settimeout(0.25)
                    while detener is None or not detener.is_set():
                        try:
                            conexion, _ = servidor.accept()
                        except TimeoutError:
                            continue
                        with conexion:
                            conexion.settimeout(8)
                            try:
                                uid = _uid_par(conexion)
                                if uid not in {self.config.uid_agente, self.uid_escritor}:
                                    raise ValueError("La identidad local no está registrada para este servicio.")
                                via = self.procesar(_recibir(conexion), uid=uid)
                            except (OSError, ValueError, EOFError) as exc:
                                via = _error(exc)
                            try:
                                _enviar(conexion, via)
                            except (OSError, ValueError):
                                continue
                finally:
                    ruta.unlink()


def _retirar_socket_huerfano(ruta):
    try:
        datos = ruta.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(datos.st_mode) or datos.st_uid != os.geteuid():
        raise ValueError(f"La ruta del socket está ocupada: {ruta}")
    with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as cliente:
        cliente.settimeout(1)
        try:
            cliente.connect(str(ruta))
        except ConnectionRefusedError:
            ruta.unlink()
            return
    raise FileExistsError(f"El servicio ya escucha en el socket: {ruta}")


def _uid_par(conexion):
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        funcion = libc.getpeereid
        funcion.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        funcion.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if funcion(conexion.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return uid.value
    if sys.platform.startswith("linux"):
        formato = struct.Struct("=iII")
        _, uid, _ = formato.unpack(conexion.getsockopt(unix_socket.SOL_SOCKET, unix_socket.SO_PEERCRED, formato.size))
        return uid
    raise ValueError("El sistema no ofrece una credencial local de proceso soportada.")


def _bloque(conexion, tamano):
    datos = bytearray()
    while len(datos) < tamano:
        recibido = conexion.recv(tamano - len(datos))
        if not recibido:
            raise EOFError("La conexión se cerró antes de recibir un mensaje completo.")
        datos.extend(recibido)
    return bytes(datos)


def _recibir(conexion):
    tamano = int.from_bytes(_bloque(conexion, 4), byteorder="big")
    if not 0 < tamano <= _MAX_MENSAJE:
        raise ValueError("El tamaño de la solicitud local no está permitido.")
    try:
        return json_estricto(_bloque(conexion, tamano).decode("utf-8"))
    except RecursionError as exc:
        raise ValueError("El mensaje JSON excede la profundidad admitida.") from exc


def _enviar(conexion, mensaje):
    datos = _json(mensaje)
    if not 0 < len(datos) <= _MAX_MENSAJE:
        raise ValueError("El mensaje supera el tamaño admitido por el servicio.")
    conexion.sendall(len(datos).to_bytes(4, byteorder="big") + datos)


def solicitar_sdd(socket, solicitud):
    """Cliente. Si el servicio falta, la escritura permanece bloqueada."""
    try:
        with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as conexion:
            conexion.settimeout(30)
            conexion.connect(str(socket))
            _enviar(conexion, solicitud)
            respuesta = _recibir(conexion)
            if not isinstance(respuesta, dict) or type(respuesta.get("codigo")) is not int:
                raise ValueError("Respuesta inválida del servicio SDD.")
            return respuesta
    except (OSError, ValueError, EOFError, TypeError, RecursionError) as exc:
        return _error(exc)
