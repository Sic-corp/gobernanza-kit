"""Instantáneas Git exactas y temporales; F-0103@r1.

worktree incluye archivos versionados y nuevos no ignorados; staged lee el índice;
REF lee blobs del commit. No aplica filtros, hooks ni checkout. Los ignorados que
ya están versionados siguen incluidos. Los enlaces absolutos, gitlinks, conflictos
y rutas que requieren atravesar un ancestro enlazado se rechazan explícitamente.
La captura de un worktree presupone un escritor cooperativo; no bloquea procesos.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
import subprocess
import tempfile
import unicodedata


class ErrorArbol(ValueError):
    """El árbol solicitado no puede materializarse con seguridad."""


@dataclass(frozen=True)
class Arbol:
    raiz: Path
    huella: str
    archivos: dict
    origen: str
    commit: str | None


def _git(raiz, *argumentos):
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    entorno.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    try:
        proceso = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
             *argumentos],
            cwd=raiz, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ErrorArbol(f"No se pudo leer Git: {exc}") from exc
    if proceso.returncode:
        mensaje = proceso.stderr.decode("utf-8", errors="replace").strip()
        raise ErrorArbol(f"Git rechazó la lectura del árbol: {mensaje}")
    return proceso.stdout


def _raiz_repositorio(raiz):
    try:
        raiz = Path(raiz).resolve(strict=True)
        if not raiz.is_dir():
            raise ErrorArbol("La raíz debe ser un directorio de trabajo Git.")
        superior = _git(raiz, "rev-parse", "--show-toplevel").rstrip(b"\n")
        if Path(os.fsdecode(superior)).resolve() != raiz:
            raise ErrorArbol("La raíz indicada pertenece a un repositorio padre; indica su raíz exacta.")
    except ErrorArbol:
        raise
    except (OSError, TypeError, RuntimeError, ValueError) as exc:
        raise ErrorArbol(f"Raíz de repositorio inválida: {exc}") from exc
    return raiz


def _ruta(texto):
    if isinstance(texto, bytes):
        try:
            texto = texto.decode("utf-8")
        except UnicodeError as exc:
            raise ErrorArbol("Las rutas del árbol deben ser UTF-8.") from exc
    partes = PurePosixPath(texto).parts if isinstance(texto, str) else ()
    if (not texto or not partes or "\x00" in texto or "\\" in texto
            or PurePosixPath(texto).is_absolute() or ".." in partes
            or PurePosixPath(texto).as_posix() != texto
            or any(p.casefold() == ".git" for p in partes)):
        raise ErrorArbol(f"Ruta Git insegura: {texto!r}")
    return texto


def _modo(modo):
    if modo not in {"100644", "100755", "120000"}:
        raise ErrorArbol(f"Modo Git no soportado: {modo}; no se admiten submódulos ni objetos especiales.")
    return modo


def _indice(raiz):
    entradas = {}
    for registro in _git(raiz, "ls-files", "--cached", "--stage", "-z").split(b"\0"):
        if not registro:
            continue
        try:
            cabecera, nombre = registro.split(b"\t", 1)
            modo, oid, etapa = cabecera.decode("ascii").split()
        except (ValueError, UnicodeError) as exc:
            raise ErrorArbol("Entrada de índice Git inválida.") from exc
        nombre = _ruta(nombre)
        if etapa != "0":
            raise ErrorArbol(f"El índice contiene un conflicto sin resolver: {nombre}")
        if nombre in entradas:
            raise ErrorArbol(f"Entrada de índice duplicada: {nombre}")
        entradas[nombre] = (_modo(modo), oid)
    return entradas


def _entradas_commit(raiz, commit):
    entradas = {}
    for registro in _git(raiz, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not registro:
            continue
        try:
            cabecera, nombre = registro.split(b"\t", 1)
            modo, tipo, oid = cabecera.decode("ascii").split()
        except (ValueError, UnicodeError) as exc:
            raise ErrorArbol("Entrada de árbol Git inválida.") from exc
        nombre = _ruta(nombre)
        modo = _modo(modo)
        if tipo != "blob" or nombre in entradas:
            raise ErrorArbol(f"Objeto Git inválido o duplicado: {nombre}")
        entradas[nombre] = (modo, oid)
    return entradas


def _blob(raiz, oid):
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid) is None:
        raise ErrorArbol("Identidad de blob inválida.")
    return _git(raiz, "cat-file", "blob", oid)


def _leer_trabajo(raiz, nombre):
    """Lee mediante dir_fd y O_NOFOLLOW: nunca abre el destino de un enlace."""
    abiertos = []
    try:
        directorio = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY)
        abiertos.append(directorio)
        partes = PurePosixPath(nombre).parts
        for parte in partes[:-1]:
            directorio = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directorio)
            abiertos.append(directorio)
        hoja = partes[-1]
        datos = os.stat(hoja, dir_fd=directorio, follow_symlinks=False)
        if stat.S_ISLNK(datos.st_mode):
            return "120000", os.fsencode(os.readlink(hoja, dir_fd=directorio))
        if not stat.S_ISREG(datos.st_mode):
            raise ErrorArbol(f"El worktree contiene un objeto especial: {nombre}")
        archivo = os.open(hoja, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directorio)
        abiertos.append(archivo)
        estado = os.fstat(archivo)
        if not stat.S_ISREG(estado.st_mode):
            raise ErrorArbol(f"El objeto cambió durante su lectura: {nombre}")
        with os.fdopen(os.dup(archivo), "rb") as flujo:
            contenido = flujo.read()
        return ("100755" if estado.st_mode & 0o111 else "100644"), contenido
    except FileNotFoundError:
        return None  # Un archivo ausente en worktree representa un borrado.
    except OSError as exc:
        raise ErrorArbol(f"No se puede leer {nombre} sin atravesar enlaces: {exc}") from exc
    finally:
        for descriptor in reversed(abiertos):
            os.close(descriptor)


def _clave_portable(nombre):
    """Una sola equivalencia conservadora para rutas, ancestros y enlaces."""
    return unicodedata.normalize("NFC", nombre).casefold()


def _validar_captura(captura):
    destinos = {}
    enlaces = {}
    for nombre, (modo, contenido) in captura.items():
        _ruta(nombre)
        normalizado = _clave_portable(nombre)
        if normalizado in destinos:
            raise ErrorArbol(f"Rutas incompatibles en un sistema de archivos insensible a mayúsculas: {nombre}")
        destinos[normalizado] = nombre
    for nombre, (modo, contenido) in captura.items():
        for padre in PurePosixPath(nombre).parents:
            if _clave_portable(padre.as_posix()) in destinos:
                raise ErrorArbol(f"El árbol usa un archivo o enlace como ancestro: {nombre}")
        if modo == "120000":
            try:
                destino = contenido.decode("utf-8")
            except UnicodeError as exc:
                raise ErrorArbol(f"Destino de enlace no UTF-8: {nombre}") from exc
            if (not destino or "\x00" in destino or "\\" in destino
                    or PurePosixPath(destino).is_absolute()):
                raise ErrorArbol(f"Destino de enlace inseguro: {nombre}")
            enlaces[_clave_portable(nombre)] = destino

    # Resuelve únicamente el grafo capturado, no los enlaces del checkout origen.
    for clave, destino in enlaces.items():
        nombre = destinos[clave]
        pendientes = list(PurePosixPath(clave).parent.parts) + destino.split("/")
        resueltas, visitados = [], {clave}
        while pendientes:
            parte = pendientes.pop(0)
            if parte in {"", "."}:
                continue
            if parte == "..":
                if not resueltas:
                    raise ErrorArbol(f"El enlace sale de la raíz: {nombre}")
                resueltas.pop()
                continue
            parte = _clave_portable(parte)
            if parte == ".git":
                raise ErrorArbol(f"El enlace apunta a metadatos Git: {nombre}")
            resueltas.append(parte)
            actual = "/".join(resueltas)
            if actual in enlaces:
                if actual in visitados:
                    raise ErrorArbol(f"Ciclo de enlaces: {nombre}")
                visitados.add(actual)
                resueltas.pop()
                pendientes = enlaces[actual].split("/") + pendientes


def _capturar(raiz, arbol):
    commit = None
    if arbol in {"worktree", "staged"}:
        entradas = _indice(raiz)
    else:
        commit = _git(raiz, "rev-parse", "--verify", "--end-of-options", arbol + "^{commit}").strip().decode("ascii")
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
            raise ErrorArbol("Referencia Git sin identidad de commit inequívoca.")
        entradas = _entradas_commit(raiz, commit)
    if arbol == "worktree":
        nombres = set(entradas)
        for nombre in _git(raiz, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if nombre:
                nombres.add(_ruta(nombre))
        captura = {}
        for nombre in sorted(nombres):
            leido = _leer_trabajo(raiz, nombre)
            if leido is not None:
                captura[nombre] = leido
    else:
        captura = {nombre: (modo, _blob(raiz, oid)) for nombre, (modo, oid) in sorted(entradas.items())}
    _validar_captura(captura)
    return captura, commit


@contextmanager
def materializar(raiz, arbol="worktree"):
    """Entrega una copia independiente y la retira al salir, aun ante excepción.

    No cambia el origen ni conserva .git. La huella canónica solo cubre las rutas,
    modos y SHA-256 de los bytes; no incorpora mtime, selector o ruta temporal.
    .commit solo identifica selectores REF, nunca una captura staged o worktree.
    """
    if not isinstance(arbol, str) or not arbol or "\x00" in arbol:
        raise ErrorArbol("El selector debe ser worktree, staged o una referencia Git no vacía.")
    raiz = _raiz_repositorio(raiz)
    captura, commit = _capturar(raiz, arbol)
    archivos = {nombre: {"sha256": hashlib.sha256(contenido).hexdigest(), "modo": modo}
                for nombre, (modo, contenido) in sorted(captura.items())}
    canonico = json.dumps(archivos, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    huella = hashlib.sha256(canonico).hexdigest()
    try:
        temporal = tempfile.TemporaryDirectory(prefix="gobernanza-arbol-")
    except OSError as exc:
        raise ErrorArbol(f"No se pudo preparar el directorio temporal: {exc}") from exc
    try:
        destino = Path(temporal.name)
        try:
            for nombre, (modo, contenido) in sorted(captura.items()):
                archivo = destino / nombre
                archivo.parent.mkdir(parents=True, exist_ok=True)
                if modo == "120000":
                    archivo.symlink_to(contenido.decode("utf-8"))
                else:
                    archivo.write_bytes(contenido)
                    archivo.chmod(0o755 if modo == "100755" else 0o644)
        except OSError as exc:
            raise ErrorArbol(f"No se pudo materializar la copia temporal: {exc}") from exc
        yield Arbol(destino, huella, archivos, arbol, commit)
    finally:
        temporal.cleanup()


def huella_arbol(raiz, arbol="worktree"):
    with materializar(raiz, arbol) as copia:
        return copia.huella


def commit_lectura(raiz, ref):
    """Resuelve una ref, abreviatura o SHA literal sin ejecutar helpers."""
    if (not isinstance(ref, str) or not ref or ref.startswith("-")
            or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", ref) or "@{" in ref):
        raise ErrorArbol(f"Referencia Git insegura: {ref!r}.")
    valor = _git(raiz, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
    if re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", valor) is None:
        raise ErrorArbol(f"Referencia sin commit inequívoco: {ref!r}.")
    return valor.decode("ascii")


class LectorArbol:
    """Inventario de un árbol y lectura de archivos regulares por ruta exacta."""

    def __init__(self, raiz, arbol):
        self.raiz = _raiz_repositorio(raiz)
        self.arbol = arbol
        self.commit = None
        if arbol in ("worktree", "staged"):
            self.entradas = _indice(self.raiz)
        else:
            self.commit = commit_lectura(self.raiz, arbol)
            self.entradas = _entradas_commit(self.raiz, self.commit)
        self.rutas = set(self.entradas)
        if arbol == "worktree":
            nuevos = _git(self.raiz, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
            self.rutas.update(_ruta(nombre) for nombre in nuevos if nombre)
        self.portables = {}
        for ruta in self.rutas:
            partes = PurePosixPath(ruta).parts
            for fin in range(1, len(partes) + 1):
                nombre = "/".join(partes[:fin])
                clave = _clave_portable(nombre)
                if clave in self.portables and self.portables[clave] != nombre:
                    raise ErrorArbol(f"Alias portable ambiguo: {self.portables[clave]} y {nombre}.")
                self.portables[clave] = nombre

    def comprobar_ruta(self, ruta):
        nombre = _ruta(ruta)
        partes = PurePosixPath(nombre).parts
        for fin in range(1, len(partes) + 1):
            ancestro = "/".join(partes[:fin])
            conocido = self.portables.get(_clave_portable(ancestro))
            if conocido is not None and conocido != ancestro:
                raise ErrorArbol(f"Alias de ruta: {ancestro} respecto de {conocido}.")
            if self.entradas.get(ancestro, (None,))[0] == "120000":
                raise ErrorArbol(f"Ruta enlazada fuera de la lectura regular: {ancestro}.")
        if self.arbol == "worktree":
            comprobar_ruta_trabajo(self.raiz, nombre)
        return nombre

    def entrada(self, ruta):
        nombre = self.comprobar_ruta(ruta)
        if self.arbol == "worktree":
            # La configuración puede estar excluida de Git, pero se coteja
            # expresamente como archivo de trabajo durante la selección.
            if nombre not in self.rutas and nombre != "gobernanza/config.json":
                return None
            imagen = _leer_trabajo(self.raiz, nombre)
            if imagen is None:
                return None
            modo, contenido = imagen
        else:
            entrada = self.entradas.get(nombre)
            if entrada is None:
                return None
            modo, blob = entrada
            contenido = _blob(self.raiz, blob)
        if modo not in ("100644", "100755"):
            raise ErrorArbol(f"Se requiere un archivo regular: {nombre}.")
        return modo, contenido

    def leer(self, ruta):
        entrada = self.entrada(ruta)
        if entrada is None:
            raise ErrorArbol(f"Archivo ausente en {self.arbol}: {ruta}.")
        return entrada[1]

    def listar(self, prefijo=""):
        if prefijo:
            self.comprobar_ruta(prefijo.rstrip("/"))
        return tuple(sorted(ruta for ruta in self.rutas if ruta.startswith(prefijo)))

    def blob(self, ruta, contenido, *, longitud):
        if self.arbol != "worktree":
            return self.entradas[ruta][1]
        formato = hashlib.sha256 if longitud == 64 else hashlib.sha1
        return formato(f"blob {len(contenido)}\0".encode() + contenido).hexdigest()


def comprobar_ruta_trabajo(raiz, nombre):
    """Inspecciona el destino o prefijo sin seguir enlaces ni abrir su contenido."""
    abiertos = []
    try:
        directorio = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY)
        abiertos.append(directorio)
        partes = PurePosixPath(_ruta(nombre)).parts
        for parte in partes[:-1]:
            directorio = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directorio)
            abiertos.append(directorio)
        modo = os.stat(partes[-1], dir_fd=directorio, follow_symlinks=False).st_mode
        if not (stat.S_ISREG(modo) or stat.S_ISDIR(modo)):
            raise ErrorArbol(f"Destino efectivo no regular: {nombre}.")
    except FileNotFoundError:
        # Una ruta nueva sigue siendo válida cuando no hay ancestros enlazados.
        pass
    except OSError as exc:
        raise ErrorArbol(f"Destino efectivo inseguro: {nombre}: {exc}.") from exc
    finally:
        for descriptor in reversed(abiertos):
            os.close(descriptor)
