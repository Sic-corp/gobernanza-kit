"""Comprobaciones del montaje protegido de SDD y de su árbol Git aceptado."""

from contextlib import contextmanager, ExitStack
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from .arboles import ErrorArbol, LectorArbol, _clave_portable, _git


RAICES_SDD = ("sdd", "gobernanza/sdd")
REF_SDD_ACEPTADA = "refs/heads/sdd-aceptada"
_SHA_GIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ErrorProteccionSDD(ValueError):
    """El escritor no puede asegurar la protección de SDD."""


def _raices(raices):
    if not isinstance(raices, (list, tuple)) or tuple(raices) not in (("sdd",), RAICES_SDD):
        raise ErrorProteccionSDD("Declara sdd o ambas raíces sdd y gobernanza/sdd.")
    return tuple(raices)


class _EstadisticasMontaje(ctypes.Structure):
    # ABI de struct statfs de Darwin con inodos de 64 bits, de <sys/mount.h>.
    _fields_ = [
        ("tam_bloque", ctypes.c_uint32), ("tam_io", ctypes.c_int32),
        ("bloques_archivos", ctypes.c_uint64 * 5), ("fsid", ctypes.c_int32 * 2),
        ("propietario", ctypes.c_uint32), ("tipo", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("subtipo", ctypes.c_uint32),
        ("nombre_tipo", ctypes.c_char * 16), ("destino", ctypes.c_char * 1024),
        ("origen", ctypes.c_char * 1024), ("flags_ext", ctypes.c_uint32),
        ("reservado", ctypes.c_uint32 * 7),
    ]


class _PermisosDarwin:
    def __init__(self):
        if sys.platform != "darwin":
            raise ErrorProteccionSDD("El perfil de montaje protegido requiere macOS.")
        try:
            biblioteca = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            self.acl = biblioteca.acl_get_fd_np
            self.acl.argtypes = [ctypes.c_int, ctypes.c_int]
            self.acl.restype = ctypes.c_void_p
            self.liberar_acl = biblioteca.acl_free
            self.liberar_acl.argtypes = [ctypes.c_void_p]
            self.liberar_acl.restype = ctypes.c_int
            self.estadisticas = getattr(biblioteca, "fstatfs$INODE64", None) or biblioteca.fstatfs
            self.estadisticas.argtypes = [ctypes.c_int, ctypes.POINTER(_EstadisticasMontaje)]
            self.estadisticas.restype = ctypes.c_int
        except (AttributeError, OSError) as exc:
            raise ErrorProteccionSDD("No se pueden comprobar ACL y montaje de macOS.") from exc
        self.volumenes = set()

    def comprobar(self, fd, estado, ruta):
        if estado.st_dev not in self.volumenes:
            montaje = _EstadisticasMontaje()
            if self.estadisticas(fd, ctypes.byref(montaje)) != 0:
                raise ErrorProteccionSDD(f"No se puede comprobar el montaje de {ruta}.")
            # MNT_LOCAL y MNT_IGNORE_OWNERSHIP de <sys/mount.h>.
            if not montaje.flags & 0x00001000 or montaje.flags & 0x00200000:
                raise ErrorProteccionSDD(f"{ruta} requiere un volumen local que respete la propiedad por UID.")
            self.volumenes.add(estado.st_dev)
        ctypes.set_errno(0)
        acl = self.acl(fd, 0x100)  # ACL_TYPE_EXTENDED de <sys/acl.h>
        if acl is not None:
            self.liberar_acl(acl)
            raise ErrorProteccionSDD(f"{ruta} tiene una ACL extendida fuera del perfil POSIX comprobado.")
        if ctypes.get_errno() != errno.ENOENT:
            raise ErrorProteccionSDD(f"No se puede descartar una ACL extendida en {ruta}.")


@contextmanager
def _abrir(nombre, ruta, *, padre=None, directorio=True):
    banderas = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directorio:
        banderas |= os.O_DIRECTORY
    try:
        fd = os.open(nombre, banderas, dir_fd=padre)
    except OSError as exc:
        raise ErrorProteccionSDD(f"No se puede abrir {ruta} sin seguir enlaces: {exc}.") from exc
    try:
        yield fd
    finally:
        os.close(fd)


class _ProteccionDisco:
    def __init__(self, escritor):
        self.escritor = escritor
        self.darwin = _PermisosDarwin()

    def comprobar(self, fd, ruta, *, ancestro=False, directorio=True):
        estado = os.fstat(fd)
        if directorio and not stat.S_ISDIR(estado.st_mode):
            raise ErrorProteccionSDD(f"{ruta} debe ser un directorio.")
        if not directorio and (not stat.S_ISREG(estado.st_mode) or estado.st_nlink != 1):
            raise ErrorProteccionSDD(f"{ruta} requiere un archivo regular sin enlaces duros.")
        propietarios = {0, self.escritor} if ancestro else {self.escritor}
        if estado.st_uid not in propietarios:
            raise ErrorProteccionSDD(f"{ruta} tiene un propietario ajeno al escritor de confianza.")
        if estado.st_mode & 0o022 and not (ancestro and estado.st_mode & stat.S_ISVTX):
            raise ErrorProteccionSDD(f"{ruta} permite escritura o reemplazo por un UID ajeno al escritor.")
        self.darwin.comprobar(fd, estado, ruta)
        return estado

    @contextmanager
    def abrir_padre(self, ruta):
        with ExitStack() as descriptores:
            recorrido = Path("/")
            actual = descriptores.enter_context(_abrir("/", recorrido))
            self.comprobar(actual, recorrido, ancestro=True)
            for nombre in ruta.parent.parts[1:]:
                recorrido /= nombre
                actual = descriptores.enter_context(_abrir(nombre, recorrido, padre=actual))
                self.comprobar(actual, recorrido, ancestro=True)
            yield actual

    def raiz_sdd(self, fd, ruta, partes):
        nombre, *resto = partes
        destino = ruta / nombre
        with _abrir(nombre, destino, padre=fd) as siguiente:
            if resto:
                self.comprobar(siguiente, destino, ancestro=True)
                self.raiz_sdd(siguiente, destino, resto)
            else:
                self.comprobar(siguiente, destino)
                self.contenido(siguiente, destino)

    def reservar_ausente(self, fd, ruta, partes):
        nombre, *resto = partes
        destino = ruta / nombre
        try:
            os.stat(nombre, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            # Una entrada que todavía no existe no disfruta de protección sticky.
            if os.fstat(fd).st_mode & 0o022:
                raise ErrorProteccionSDD(f"{ruta} permite crear {destino} fuera de la API.")
            return
        if not resto:
            raise ErrorProteccionSDD(f"La raíz existente {destino} requiere quedar protegida.")
        with _abrir(nombre, destino, padre=fd) as siguiente:
            self.comprobar(siguiente, destino, ancestro=True)
            self.reservar_ausente(siguiente, destino, resto)

    def contenido(self, fd, ruta):
        for nombre in os.listdir(fd):
            destino = ruta / nombre
            modo = os.stat(nombre, dir_fd=fd, follow_symlinks=False).st_mode
            directorio = stat.S_ISDIR(modo)
            if not directorio and not stat.S_ISREG(modo):
                raise ErrorProteccionSDD(f"{destino} no es un archivo o directorio regular.")
            with _abrir(nombre, destino, padre=fd, directorio=directorio) as siguiente:
                self.comprobar(siguiente, destino, directorio=directorio)
                if directorio:
                    self.contenido(siguiente, destino)


def _escritor(uid_agente, uid_escritor=None):
    if sys.platform != "darwin":
        raise ErrorProteccionSDD("El perfil de montaje protegido requiere macOS.")
    ejecutor = os.geteuid()
    escritor = ejecutor if uid_escritor is None else uid_escritor
    if (type(uid_agente) is not int or type(escritor) is not int or escritor != ejecutor
            or not 0 < uid_agente < 2**32 - 1 or not 0 < escritor < 2**32 - 1 or uid_agente == escritor):
        raise ErrorProteccionSDD("El escritor ejecutor y el agente deben usar UID no privilegiados distintos.")
    return escritor


def _ruta_fisica(valor):
    ruta = Path(valor)
    if ruta.anchor != "/" or len(ruta.parts) < 2 or ".." in ruta.parts:
        raise ErrorProteccionSDD("Se requiere una ruta absoluta física con nombre propio.")
    return ruta


def verificar_permisos_sdd(raiz, *, uid_agente, uid_escritor=None, raices=RAICES_SDD):
    """Coteja la separación POSIX de una copia local preparada por el dueño.

    Las entradas de los ancestros solo pueden ser reemplazadas por identidades
    de confianza. Un directorio sticky permite cambios ajenos entre hermanos
    sin ceder el siguiente componente, cuyo propietario se comprueba también.
    No instala permisos ni acredita las credenciales del proceso agente.
    """
    protecciones = _raices(raices)
    ruta = _ruta_fisica(raiz)
    control = _ProteccionDisco(_escritor(uid_agente, uid_escritor))
    try:
        with control.abrir_padre(ruta) as padre, _abrir(ruta.name, ruta, padre=padre) as fd:
            control.comprobar(fd, ruta, ancestro=True)
            for protegida in protecciones:
                control.raiz_sdd(fd, ruta, protegida.split("/"))
            if len(protecciones) == 1:
                control.reservar_ausente(fd, ruta, ("gobernanza", "sdd"))
    except OSError as exc:
        raise ErrorProteccionSDD(f"No se pudo comprobar la protección de {ruta}: {exc}.") from exc


def verificar_almacen_sdd(ruta, *, uid_agente, privado):
    """Comprueba un archivo o directorio de configuración, referencia o estado.

    Para el socket se comprueba su directorio con ``privado=False``. Así se
    permite acceso de lectura y recorrido sin permitir crear otras entradas.
    """
    ruta = _ruta_fisica(ruta)
    control = _ProteccionDisco(_escritor(uid_agente))
    try:
        with control.abrir_padre(ruta) as padre:
            modo = os.stat(ruta.name, dir_fd=padre, follow_symlinks=False).st_mode
            directorio = stat.S_ISDIR(modo)
            if not directorio and not stat.S_ISREG(modo):
                raise ErrorProteccionSDD(f"{ruta} requiere un archivo o directorio regular sin enlaces.")
            with _abrir(ruta.name, ruta, padre=padre, directorio=directorio) as fd:
                estado = control.comprobar(fd, ruta, directorio=directorio)
                if privado and estado.st_mode & 0o077:
                    raise ErrorProteccionSDD(f"{ruta} debe ser un almacén privado del escritor.")
    except OSError as exc:
        raise ErrorProteccionSDD(f"No se pudo comprobar el almacén {ruta}: {exc}.") from exc


def _config_git_autocontenida(contenido):
    # Usa el parser nativo sin descubrir un repo, leer includes o cargar config ajena.
    proceso = subprocess.run(
        ["/usr/bin/git", "config", "--no-includes", "--null", "--file", "-", "--list"],
        input=contenido, capture_output=True, cwd="/", timeout=15,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": os.devnull},
    )
    if proceso.returncode != 0:
        raise ErrorProteccionSDD("La configuración Git de autoridad no se puede interpretar.")
    externos = {b"include.path", b"core.worktree", b"extensions.worktreeconfig", b"extensions.partialclone"}
    for registro in proceso.stdout.split(b"\x00"):
        clave = registro.partition(b"\n")[0].lower()
        if (clave in externos or clave.startswith(b"includeif.")
                or clave.startswith(b"remote.") and clave.endswith(b".promisor")):
            raise ErrorProteccionSDD(f"La autoridad Git no admite configuración externa: {os.fsdecode(clave)}.")


def verificar_autoridad_git(ruta, *, raiz_agente, uid_agente):
    """Exige un checkout Git independiente, autocontenido y privado del escritor."""
    ruta = _ruta_fisica(ruta)
    agente = _ruta_fisica(raiz_agente)
    claves = sorted((_clave_portable(ruta.as_posix()), _clave_portable(agente.as_posix())), key=len)
    if claves[0] == claves[1] or claves[1].startswith(claves[0] + "/"):
        raise ErrorProteccionSDD("La autoridad Git requiere una copia distinta e independiente del checkout agente.")
    control = _ProteccionDisco(_escritor(uid_agente))
    git = ruta / ".git"
    try:
        with control.abrir_padre(ruta) as padre:
            estado = control.comprobar(padre, ruta.parent)
            if stat.S_IMODE(estado.st_mode) != 0o700:
                raise ErrorProteccionSDD("La copia de autoridad requiere un padre privado con modo 0700.")
            with _abrir(ruta.name, ruta, padre=padre) as checkout:
                control.comprobar(checkout, ruta)
                with _abrir(".git", git, padre=checkout) as metadatos:
                    control.comprobar(metadatos, git)
                    control.contenido(metadatos, git)
                    reservados = ("commondir", "gitdir", "worktrees", "config.worktree", "info/grafts",
                                  "objects/info/alternates", "objects/info/http-alternates")
                    for nombre in reservados:
                        try:
                            os.stat(nombre, dir_fd=metadatos, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        raise ErrorProteccionSDD(f"La autoridad Git no admite el metadato externo {nombre}.")
                    with _abrir("config", git / "config", padre=metadatos, directorio=False) as fd:
                        with os.fdopen(os.dup(fd), "rb") as archivo:
                            contenido = archivo.read(1024 * 1024 + 1)
                    if len(contenido) > 1024 * 1024:
                        raise ErrorProteccionSDD("La configuración Git de autoridad excede el tamaño admitido.")
        _config_git_autocontenida(contenido)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErrorProteccionSDD(f"No se pudo comprobar la autoridad Git {ruta}: {exc}.") from exc


def _git_sha(sha):
    if not isinstance(sha, str) or _SHA_GIT.fullmatch(sha) is None:
        raise ErrorProteccionSDD("Se requiere el SHA completo y literal de un commit Git.")
    return sha


def capturar_imagen_sdd(raiz_git, commit, *, raices=RAICES_SDD):
    """Lee los archivos SDD de un commit exacto en el repositorio de autoridad."""
    protegidas = _raices(raices)
    _git_sha(commit)
    imagen = {}
    try:
        lector = LectorArbol(raiz_git, commit)
        if lector.commit != commit:
            raise ErrorProteccionSDD("El SHA debe identificar directamente el commit candidato.")
        for raiz in RAICES_SDD:
            lector.comprobar_ruta(raiz)
            if raiz in lector.rutas:
                raise ErrorProteccionSDD(f"La raíz {raiz} debe ser un directorio en el candidato Git.")
            rutas = lector.listar(f"{raiz}/")
            if raiz not in protegidas and rutas:
                raise ErrorProteccionSDD(f"La raíz existente {raiz} requiere quedar protegida.")
            for ruta in rutas:
                modo, contenido = lector.entrada(ruta)
                imagen[ruta] = {"modo": modo, "sha256": hashlib.sha256(contenido).hexdigest()}
    except ErrorArbol as exc:
        raise ErrorProteccionSDD(str(exc)) from exc
    return imagen


def verificar_candidato_sdd(raiz_git, candidato, esperado, *, raices=RAICES_SDD):
    """Coteja rutas, modos y SHA-256 con la imagen completa de la autoridad."""
    if not isinstance(esperado, dict) or any(
        not isinstance(ruta, str) or not isinstance(archivo, dict)
        or archivo.keys() != {"modo", "sha256"} or archivo["modo"] not in ("100644", "100755")
        or not isinstance(archivo["sha256"], str) or _SHA256.fullmatch(archivo["sha256"]) is None
        for ruta, archivo in esperado.items()
    ):
        raise ErrorProteccionSDD("La imagen esperada de SDD requiere rutas, modos y huellas SHA-256.")
    real = capturar_imagen_sdd(raiz_git, candidato, raices=raices)
    diferencias = sorted(ruta for ruta in real.keys() | esperado.keys() if real.get(ruta) != esperado.get(ruta))
    if diferencias:
        raise ErrorProteccionSDD(f"El candidato difiere de la imagen autorizada de SDD: {', '.join(diferencias)}.")


def aceptar_candidato_sdd(raiz_git, candidato, esperado, *, base, destino=REF_SDD_ACEPTADA, raices=RAICES_SDD):
    """Promueve el candidato cotejado en una ref exclusiva del repositorio de autoridad."""
    _git_sha(base)
    verificar_candidato_sdd(raiz_git, candidato, esperado, raices=raices)
    if not isinstance(destino, str) or not re.fullmatch(r"refs/heads/sdd-aceptada(?:[-/][a-z0-9._/-]+)?", destino):
        raise ErrorProteccionSDD("El destino debe ser una referencia reservada sdd-aceptada.")
    try:
        _git(raiz_git, "check-ref-format", destino)
        base_real = _git(raiz_git, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
        if base_real != base:
            raise ErrorProteccionSDD("La base debe identificar directamente un commit Git.")
        try:
            _git(raiz_git, "merge-base", "--is-ancestor", base, candidato)
        except ErrorArbol as exc:
            raise ErrorProteccionSDD("El candidato no desciende de la base autorizada.") from exc
        ocupados = _git(raiz_git, "worktree", "list", "--porcelain", "-z").split(b"\x00")
        if os.fsencode(f"branch {destino}") in ocupados:
            raise ErrorProteccionSDD("El destino de autoridad no puede estar activo en un checkout.")
        referencias = _git(raiz_git, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)", destino)
        anterior = "0" * len(base)
        for linea in referencias.decode().splitlines():
            nombre, sha, simbolica = linea.split("\x00")
            if nombre == destino:
                if simbolica or sha != base:
                    raise ErrorProteccionSDD("La referencia de autoridad ya no coincide con la base esperada.")
                anterior = sha
        _git(raiz_git, "-c", "core.hooksPath=/dev/null", "update-ref", "--no-deref", destino, candidato, anterior)
    except ErrorArbol as exc:
        raise ErrorProteccionSDD(f"No se pudo avanzar la referencia de autoridad: {exc}.") from exc
    return candidato
