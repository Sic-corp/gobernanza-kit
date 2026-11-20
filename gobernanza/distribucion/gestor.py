"""Gestión local por versiones completas y diario recuperable; protocolo 1.

Solo modifica rutas propias y un bloque AGENTS. No crea configuración, acuerdos,
commits o refs. flock coordina escritores cooperativos POSIX; no se promete una
transacción física de varios archivos ante corte eléctrico ni defensa anti-dueño.
"""

import ast
import base64
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from ..nucleo.arboles import _clave_portable, _raiz_repositorio, _ruta
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import _padre
from ..nucleo.modelo import diagnostico, resultado
from ..nucleo.verificacion import _hash
from .paquete import CAPACIDAD_UBICABLE, NAVEGACION, RECURSOS, validar_paquete
from . import sustitucion


BASE = ".gobernanza-kit"
DIARIO = BASE + "/transaccion.json"
PUENTE = "gobernanza/__init__.py"
ADMINISTRADOR = BASE + "/gestionar.py"
CAPACIDAD_AISLADA = "contenido/gobernanza/distribucion/operacion.py"
MAPA_UBICABLE = "gobernanza/rutas-kit.json"
DIARIO_UBICABLE = "gobernanza/.rutas-kit-transaccion.json"
BLOQUEO_UBICABLE = "gobernanza/.rutas-kit-operacion.lock"
ENTRADAS = {
    PUENTE: "entradas/inicio.py",
    ADMINISTRADOR: "entradas/gestionar.py",
    ".agents/skills/gobernanza-local/SKILL.md": "entradas/SKILL.md",
}
ENTRADAS_POR_MODO = {
    "estandar": ENTRADAS,
    "aislado": {ruta: entrada for ruta, entrada in ENTRADAS.items() if ruta != PUENTE},
}
INICIO, FIN = b"<!-- gobernanza-kit:inicio -->", b"<!-- gobernanza-kit:fin -->"
MARCA_ARRANQUE = b"<!-- gobernanza-kit:arranque-por-objetivo -->"
MARCA_SDD = b"<!-- gobernanza-kit:sdd-en-agents -->"
HOOK_SOLUCION = ".codex/hooks.json"
CAPACIDAD_HOOK = "contenido/gobernanza/distribucion/hook_solucion.py"
LANZADOR = "gobernanza-kit"
CAPACIDAD_LANZADOR = "contenido/gobernanza/distribucion/lanzador.py"
BLOQUE = (INICIO + b"\nSigue la skill local [.agents/skills/gobernanza-local/SKILL.md]"
          b"(.agents/skills/gobernanza-local/SKILL.md).\n" + FIN)
BLOQUE_AISLADO = (BLOQUE[:-len(FIN)]
                  + b"Modo aislado: ejecuta los verbos del kit con `python3 .gobernanza-kit/gestionar.py operar`.\n"
                  + FIN)
FASES = {"preparado", "version_lista", "entradas_publicadas", "selector_publicado", "purga_confirmada"}


class ErrorGestor(ValueError):
    pass


def _base_ubicable(base):
    if (not isinstance(base, str) or not re.fullmatch(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*", base)):
        raise ErrorGestor("La raíz de instalación debe ser una ruta relativa portable.")
    _ruta(base)
    protegidas = (BASE, "AGENTS.md", PUENTE, MAPA_UBICABLE, DIARIO_UBICABLE, BLOQUEO_UBICABLE,
                  "gobernanza/config.json", "gobernanza/hooks", "gobernanza/adaptadores",
                  ".githooks", ".codex", ".claude", ".agents/skills/gobernanza-local")
    portable = _clave_portable(base)
    for ruta in map(_clave_portable, protegidas):
        if portable == ruta or portable.startswith(ruta + "/") or ruta.startswith(portable + "/"):
            raise ErrorGestor(f"La raíz de instalación se solapa con una ruta protegida: {base}")
    return base


@dataclass(frozen=True)
class _Ubicacion:
    base: str = BASE

    @property
    def ubicable(self):
        return self.base != BASE

    @property
    def activo(self):
        return self.base + "/activo.json"

    @property
    def diario(self):
        return DIARIO_UBICABLE if self.ubicable else DIARIO

    @property
    def bloqueo(self):
        return BLOQUEO_UBICABLE if self.ubicable else self.base + "/operacion.lock"

    @property
    def administrador(self):
        return self.base + "/gestionar.py"

    @property
    def transacciones(self):
        return self.base + "/transacciones"

    def version(self, selector):
        return self.base + "/versiones/" + selector["huella_paquete"]

    def guia(self):
        return {self.base + "/skills/" + ruta.removeprefix("contenido/skill/"): ruta for ruta in NAVEGACION}

    def entradas(self, modo, *, lanzador=False):
        if self.ubicable:
            entradas = {self.administrador: CAPACIDAD_UBICABLE, self.base + "/SKILL.md": None}
        else:
            entradas = ENTRADAS_POR_MODO[modo]
        return {**entradas, LANZADOR: CAPACIDAD_LANZADOR} if lanzador else entradas

    def rutas(self, modo, navegacion=False, *, lanzador=False):
        entradas = {*self.entradas(modo, lanzador=lanzador), "AGENTS.md", self.activo}
        return entradas | self.guia().keys() if navegacion else entradas


_CLASICA = _Ubicacion()


def _imagen_entrada(slot, entrada):
    if entrada == CAPACIDAD_LANZADOR:
        codigo = _bytes(_capturar(slot, entrada))
        if not codigo.startswith(b"#!/usr/bin/env python3\n"):
            raise ErrorGestor("El paquete carece de una entrada Python ejecutable para ./gobernanza-kit.")
        ast.parse(codigo, filename=LANZADOR)
        return _imagen(codigo, 0o755)
    if entrada is not None:
        return _capturar(slot, entrada)
    fuente = _bytes(_capturar(slot, CAPACIDAD_UBICABLE)).decode("utf-8")
    for nodo in ast.parse(fuente).body:
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name) and nodo.targets[0].id == "SKILL_UBICABLE"
                and isinstance(nodo.value, ast.Constant) and isinstance(nodo.value.value, str)):
            return _imagen(nodo.value.value.encode("utf-8"))
    raise ErrorGestor("La entrada ubicable carece de la declaración de skill.")


def _mapa_ubicable(raiz):
    imagen = _capturar(raiz, MAPA_UBICABLE)
    if imagen is None:
        raise ErrorGestor(f"Falta el mapa de instalación {MAPA_UBICABLE}.")
    mapa = json_estricto(_bytes(imagen).decode("utf-8"))
    if (not isinstance(mapa, dict) or set(mapa) != {"schema", "rutas"} or type(mapa["schema"]) is not int
            or mapa["schema"] != 1 or not isinstance(mapa["rutas"], dict) or set(mapa["rutas"]) != {"instalacion"}):
        raise ErrorGestor("El mapa debe declarar schema 1 y rutas.instalacion.")
    return _Ubicacion(_base_ubicable(mapa["rutas"]["instalacion"])), _firma(imagen)


def _comprobar_ubicacion(raiz, ubicacion):
    carpeta = _segura(raiz, ubicacion.base)
    for ancestro in (carpeta, *carpeta.parents):
        if ancestro == raiz:
            break
        if os.path.lexists(ancestro / ".git"):
            raise ErrorGestor("La instalación cruza un checkout Git anidado.")
    for relativa in (ubicacion.base, ubicacion.base + "/versiones", ubicacion.transacciones):
        ruta = _segura(raiz, relativa)
        if ruta.exists() and not ruta.is_dir():
            raise ErrorGestor(f"Se esperaba un directorio de instalación: {relativa}")
    return carpeta


def _comprobar_guia(raiz, ubicacion, *, vacia=False):
    carpetas = {
        ubicacion.base + "/skills": {"navegar-gobernanza"},
        ubicacion.base + "/skills/navegar-gobernanza": {"references"},
        ubicacion.base + "/skills/navegar-gobernanza/references": set(),
    }
    for ruta, hijas in carpetas.items():
        carpeta = _segura(raiz, ruta)
        if os.path.lexists(carpeta / ".git"):
            raise ErrorGestor(f"La guía cruza un checkout Git anidado: {ruta}")
        if vacia and carpeta.is_dir() and set(os.listdir(carpeta)) - hijas:
            raise ErrorGestor(f"El directorio de navegación contiene archivos ajenos: {ruta}")


def _punto(nombre):
    """Frontera privada inyectable; producción no simula fallos ni aceptación."""


def _salida(operacion, error=None, *, raiz=None, **campos):
    errores = [] if error is None else [diagnostico(
        "DISTRIBUCION_INVALIDA", BASE, "Instalación íntegra, plan vigente y recuperación conservadora",
        str(error) or type(error).__name__, "Preserva los archivos, revisa el conflicto y planifica de nuevo o ejecuta recuperar.")]
    salida = resultado(operacion, errores)
    pendiente = False
    if raiz is not None:
        try:
            pendiente = any(os.path.lexists(Path(raiz) / r) for r in (DIARIO, DIARIO_UBICABLE))
        except (OSError, TypeError):
            pass
    salida.update(plan=None, instalado=False, transaccion_pendiente=pendiente,
                  resumen="Distribución local explícita. Conserva la configuración de gobernanza, el índice Git y las referencias.")
    salida.update(campos)
    return salida


def _segura(raiz, relativa):
    _ruta(relativa)
    actual = Path(raiz)
    for parte in PurePosixPath(relativa).parts:
        if actual.is_symlink():
            raise ErrorGestor(f"Ancestro enlazado: {relativa}")
        if actual.exists():
            if not actual.is_dir():
                raise ErrorGestor(f"Ancestro no es directorio: {relativa}")
            aliases = [n for n in os.listdir(actual) if _clave_portable(n) == _clave_portable(parte)]
            if aliases and aliases != [parte]:
                raise ErrorGestor(f"Alias NFC/casefold de ruta: {relativa}")
        actual = actual / parte
        if actual.is_symlink():
            raise ErrorGestor(f"No se siguen enlaces de distribución: {relativa}")
    return actual


def _imagen(contenido, permisos=0o644):
    return dict(sha256=hashlib.sha256(contenido).hexdigest(),
                modo="100755" if permisos & 0o111 else "100644", permisos=permisos,
                contenido_base64=base64.b64encode(contenido).decode("ascii"))


def _bytes(imagen):
    if not isinstance(imagen, dict):
        raise ErrorGestor("Respaldo de archivo inválido.")
    try:
        contenido = base64.b64decode(imagen["contenido_base64"], validate=True)
        permisos = imagen["permisos"]
        if (type(permisos) is not int or not 0 <= permisos <= 0o777
                or imagen["modo"] != ("100755" if permisos & 0o111 else "100644")
                or hashlib.sha256(contenido).hexdigest() != imagen["sha256"]):
            raise ValueError("Hash o modo del respaldo no coincide.")
        return contenido
    except (ValueError, TypeError, KeyError) as exc:
        raise ErrorGestor(f"Respaldo no verificable: {exc}") from exc


def _capturar(raiz, relativa):
    _segura(raiz, relativa)
    try:
        with _padre(raiz, relativa) as (padre, nombre):
            previo = os.stat(nombre, dir_fd=padre, follow_symlinks=False)
            if not stat.S_ISREG(previo.st_mode):
                raise ErrorGestor(f"Archivo no regular: {relativa}")
            fd = os.open(nombre, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=padre)
            with os.fdopen(fd, "rb") as archivo:
                info = os.fstat(archivo.fileno())
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & ~0o777:
                    raise ErrorGestor(f"Archivo no regular o con permisos especiales: {relativa}")
                return _imagen(archivo.read(), stat.S_IMODE(info.st_mode))
    except FileNotFoundError:
        return None


def _firma(imagen):
    return None if imagen is None else {k: v for k, v in imagen.items() if k != "contenido_base64"}


def _escribir(raiz, relativa, imagen, *, exclusivo=False):
    contenido = _bytes(imagen)
    _segura(raiz, relativa)
    with _padre(raiz, relativa, crear=True) as (padre, nombre):
        temporal = ".kit-" + uuid.uuid4().hex + ".tmp"
        try:
            fd = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=padre)
            with os.fdopen(fd, "wb") as archivo:
                archivo.write(contenido)
                archivo.flush()
                os.fchmod(archivo.fileno(), imagen["permisos"])
                os.fsync(archivo.fileno())
            if exclusivo:
                os.link(temporal, nombre, src_dir_fd=padre, dst_dir_fd=padre, follow_symlinks=False)
            else:
                os.replace(temporal, nombre, src_dir_fd=padre, dst_dir_fd=padre)
            os.fsync(padre)
        finally:
            try: os.unlink(temporal, dir_fd=padre)
            except FileNotFoundError: pass


def _eliminar(raiz, relativa):
    _segura(raiz, relativa)
    try:
        with _padre(raiz, relativa) as (padre, nombre):
            os.unlink(nombre, dir_fd=padre)
            os.fsync(padre)
    except FileNotFoundError:
        pass


def _json(datos):
    return (json.dumps(datos, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _leer_json(raiz, relativa):
    imagen = _capturar(raiz, relativa)
    return None if imagen is None else json_estricto(_bytes(imagen).decode("utf-8"))


def _selector(manifiesto):
    return dict(schema=1, huella_paquete=manifiesto["huella_paquete"], version=manifiesto["version"], fuente_commit=manifiesto["fuente_commit"])


def _selector_valido(selector):
    if (not isinstance(selector, dict) or set(selector) != {"schema", "huella_paquete", "version", "fuente_commit"}
            or type(selector["schema"]) is not int or selector["schema"] != 1
            or not isinstance(selector["huella_paquete"], str) or not re.fullmatch(r"[a-f0-9]{64}", selector["huella_paquete"])
            or not isinstance(selector["fuente_commit"], str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", selector["fuente_commit"])
            or selector["version"] != selector["fuente_commit"]):
        raise ErrorGestor("Selector de instalación inválido.")
    return selector


def _validar_paquete(paquete):
    salida = validar_paquete(paquete)
    if salida["codigo"]:
        raise ErrorGestor("Paquete no íntegro: " + "; ".join(e["mensaje"] for e in salida["errores"]))
    return salida["manifiesto"]


def _slot(raiz, selector, ubicacion, *, validar=True):
    selector = _selector_valido(selector)
    ruta = _segura(raiz, ubicacion.version(selector))
    if validar and _selector(_validar_paquete(ruta)) != selector:
        raise ErrorGestor("El selector no identifica la versión completa conservada.")
    return ruta


def _admite_arranque(paquete):
    return MARCA_ARRANQUE in _bytes(_capturar(paquete, RECURSOS["GUIA.md"])).splitlines()


def _anuncia_sdd(paquete):
    return MARCA_SDD in _bytes(_capturar(paquete, RECURSOS["GUIA.md"])).splitlines()


def _bloque_agentes(modo, ubicacion, navegacion, *, arranque=False, sdd=False, lanzador=False):
    bloque = BLOQUE_AISLADO if modo == "aislado" else BLOQUE
    if ubicacion.ubicable:
        base = ubicacion.base
        bloque = INICIO + (
            f"\nSigue la [skill local de gobernanza]({base}/SKILL.md).\n"
            f"Usa `python3 -I {ubicacion.administrador} operar` para ejecutar los verbos del kit.\n"
        ).encode("utf-8") + FIN
    if sdd:
        bloque = bloque[:-len(FIN)] + (
            "Cuando el proyecto use el registro SDD, aplica las operaciones SDD de la skill local "
            "a sus contratos y sesiones. Conserva el plan como Markdown dentro de la sesión.\n"
        ).encode("utf-8") + FIN
    if lanzador:
        bloque = bloque[:-len(FIN)] + (
            b"Para actualizar el kit de este proyecto, ejecuta `./gobernanza-kit actualizar`.\n"
            b"Usa `--solo-plan` para revisar los cambios antes de aplicar.\n" + FIN
        )
    if not navegacion:
        return bloque
    guia = next(iter(ubicacion.guia()))
    if arranque:
        puerta = (
            f"Consulta primero la guía canónica de navegación que declare este AGENTS.md. "
            f"Si no declara otra, abre [navegar por objetivo]({guia}).\n"
            "Si el pedido y la evidencia disponible no identifican un objetivo, una pregunta o un hito concreto, "
            "pide que se precise y espera la respuesta. Hasta entonces, limita las lecturas a AGENTS.md y a esa guía.\n\n"
            "Con un objetivo concreto, sigue la orientación de la guía y abre las fuentes locales pertinentes. "
            "Cuando la acción requiera el procedimiento del kit, aplica lo siguiente.\n"
        ).encode("utf-8")
        return INICIO + b"\n" + puerta + bloque[len(INICIO) + 1:]
    return bloque[:-len(FIN)] + (
        f"Para identificar la siguiente acción de gobernanza, consulta "
        f"[navegar por objetivo]({guia}).\n"
    ).encode("utf-8") + FIN


def _anteponer_bloque(contenido, bloque):
    bom = b"\xef\xbb\xbf"
    texto = contenido.removeprefix(bom)
    prefijo = contenido[:len(contenido) - len(texto)]
    return prefijo + bloque + (b"\n\n" if texto else b"\n") + texto


def _agentes(imagen, *, instalado, modo, ubicacion=_CLASICA, navegacion=False, arranque=False,
             migracion=False, publicar=False, sdd=False, sdd_anterior=None,
             lanzador=False, lanzador_anterior=None):
    contenido = b"" if imagen is None else _bytes(imagen)
    previo = dict(sdd=sdd if sdd_anterior is None else sdd_anterior,
                  lanzador=lanzador if lanzador_anterior is None else lanzador_anterior)
    historico = _bloque_agentes(modo, ubicacion, navegacion and not migracion, **previo)
    con_arranque = _bloque_agentes(modo, ubicacion, navegacion and not migracion, arranque=arranque, **previo)
    deseado = _bloque_agentes(modo, ubicacion, navegacion, arranque=arranque, sdd=sdd, lanzador=lanzador)
    inicios, finales = contenido.count(INICIO), contenido.count(FIN)
    if not inicios and not finales:
        if instalado:
            raise ErrorGestor("Falta el bloque AGENTS gestionado.")
        if arranque:
            return _anteponer_bloque(contenido, deseado)
        return contenido + (b"\n" if contenido and not contenido.endswith(b"\n") else b"") + deseado + b"\n"
    if inicios != 1 or finales != 1 or contenido.find(INICIO) > contenido.find(FIN):
        raise ErrorGestor("Delimitadores AGENTS incompletos o ambiguos; se preserva el contenido.")
    desde, hasta = contenido.index(INICIO), contenido.index(FIN) + len(FIN)
    actual = contenido[desde:hasta]
    reconocidos = (historico, con_arranque) if migracion else (historico, con_arranque, deseado)
    if not instalado or actual not in reconocidos:
        raise ErrorGestor("Bloque AGENTS ajeno o modificado sin procedencia compatible.")
    if publicar and actual != deseado:
        if arranque and (migracion or actual != con_arranque):
            return _anteponer_bloque(contenido[:desde] + contenido[hasta:], deseado)
        return contenido[:desde] + deseado + contenido[hasta:]
    return contenido


def _namespace(raiz, instalado):
    carpeta = _segura(raiz, "gobernanza")
    if not carpeta.exists():
        return
    for actual, carpetas, hojas in os.walk(carpeta, followlinks=False):
        for nombre in carpetas + hojas:
            ruta = (Path(actual) / nombre).relative_to(raiz).as_posix()
            _segura(raiz, ruta)
        if "__pycache__" in carpetas:
            if not instalado:
                raise ErrorGestor("Bytecode Python homónimo sin procedencia.")
            carpetas.remove("__pycache__")
        for nombre in hojas:
            ruta = (Path(actual) / nombre).relative_to(raiz).as_posix()
            if nombre.endswith((".py", ".pyc")) and (not instalado or ruta != PUENTE):
                raise ErrorGestor(f"Código Python homónimo ajeno: {ruta}")


def _compatibilidad(raiz):
    config = _capturar(raiz, "gobernanza/config.json")
    if config is not None:
        datos = json_estricto(_bytes(config).decode("utf-8"))
        if not isinstance(datos, dict) or type(datos.get("schema")) is not int or datos["schema"] != 1:
            raise ErrorGestor("El esquema consumidor es incompatible; no se migra configuración.")
    return _firma(config)


def _puente_estandar(raiz, paquete):
    imagen = _capturar(raiz, PUENTE)
    return imagen is not None and imagen["sha256"] == _capturar(paquete, ENTRADAS[PUENTE])["sha256"]


def _estado(raiz, ubicacion):
    if any(_capturar(raiz, ruta) is not None for ruta in (ubicacion.diario, DIARIO if ubicacion.ubicable else DIARIO_UBICABLE)):
        raise ErrorGestor("Transacción pendiente: ejecuta recuperar con el administrador independiente.")
    imagen_activo = _capturar(raiz, ubicacion.activo)
    activo = None if imagen_activo is None else _selector_valido(json_estricto(_bytes(imagen_activo).decode("utf-8")))
    agentes = _capturar(raiz, "AGENTS.md")
    if activo is None:
        if _capturar(raiz, ubicacion.administrador) is not None:
            raise ErrorGestor("Administrador sin selector reconocido; conserva la instalación para revisión.")
        _agentes(agentes, instalado=False, modo="estandar")
        return None, None, agentes, None
    slot = _slot(raiz, activo, ubicacion)
    navegacion = (slot / NAVEGACION[0]).is_file()
    modo = "ubicable" if ubicacion.ubicable else "estandar"
    arranque = navegacion and _admite_arranque(slot)
    sdd = navegacion and _anuncia_sdd(slot)
    lanzador = (slot / CAPACIDAD_LANZADOR).is_file()
    if modo == "estandar" and agentes is not None:
        texto = _bytes(agentes)
        if any(_bloque_agentes("aislado", ubicacion, navegacion, arranque=forma, sdd=sdd, lanzador=lanzador) in texto
               for forma in (False, arranque)):
            modo = "aislado"
    _agentes(agentes, instalado=True, modo=modo, ubicacion=ubicacion, navegacion=navegacion,
             arranque=arranque, sdd=sdd, lanzador=lanzador)
    if modo == "estandar":
        _namespace(raiz, instalado=True)
    else:
        if not (slot / CAPACIDAD_AISLADA).is_file():
            raise ErrorGestor(f"La versión instalada no admite el modo {modo}.")
        if _puente_estandar(raiz, slot):
            raise ErrorGestor("Hay un puente estándar junto a un bloque aislado; revisa su procedencia.")
    entradas = ubicacion.entradas(modo, lanzador=lanzador)
    if navegacion:
        _comprobar_guia(raiz, ubicacion)
        entradas = {**entradas, **ubicacion.guia()}
    for ruta, entrada in entradas.items():
        if _capturar(raiz, ruta) != _imagen_entrada(slot, entrada):
            raise ErrorGestor(f"Entrada gestionada modificada o ausente: {ruta}")
    return activo, slot, agentes, modo


def _hook_solucion(raiz, ubicacion):
    from .hook_solucion import planificar as preparar_hook

    nuevas = preparar_hook(raiz, lanzador=ubicacion.administrador)
    if set(nuevas) != {HOOK_SOLUCION}:
        raise ErrorGestor("La activación sólo puede publicar el archivo de hooks de Codex.")
    modo, contenido = nuevas[HOOK_SOLUCION]
    if modo not in {"100644", "100755"} or not isinstance(contenido, bytes):
        raise ErrorGestor("La activación debe proporcionar una imagen regular de hooks.")
    anterior = _capturar(raiz, HOOK_SOLUCION)
    permisos = anterior["permisos"] if anterior is not None else (0o755 if modo == "100755" else 0o644)
    return {HOOK_SOLUCION: _imagen(contenido, permisos)}


def _plan(raiz, paquete, accion, modo=None, *, base_instalacion=None, migrar_navegacion=False,
          reemplazar_anteriores=False, activar_hook_solucion=False):
    if type(migrar_navegacion) is not bool or (migrar_navegacion and accion != "actualizar"):
        raise ErrorGestor("La transición de navegación requiere una actualización explícita.")
    if accion not in {"instalar", "actualizar"}:
        raise ErrorGestor("Acción inválida: usa instalar o actualizar.")
    if type(reemplazar_anteriores) is not bool or (reemplazar_anteriores and accion != "actualizar"):
        raise ErrorGestor("La retirada de slots anteriores requiere una actualización explícita.")
    if type(activar_hook_solucion) is not bool:
        raise ErrorGestor("La activación de hook debe solicitarse explícitamente.")
    manifiesto = _validar_paquete(paquete)
    nuevo = _selector(manifiesto)
    navegacion = NAVEGACION[0] in manifiesto["archivos"]
    arranque = navegacion and _admite_arranque(paquete)
    sdd = navegacion and _anuncia_sdd(paquete)
    lanzador = CAPACIDAD_LANZADOR in manifiesto["archivos"]
    if modo not in (None, "ubicable", *ENTRADAS_POR_MODO):
        raise ErrorGestor("Modo inválido: usa estandar, aislado o ubicable.")
    ubicacion, firma_mapa = _CLASICA, None
    if base_instalacion is not None and modo not in (None, "ubicable"):
        raise ErrorGestor("El plan no puede cambiar el modo de la instalación ubicable.")
    if modo == "ubicable" or base_instalacion is not None:
        ubicacion, firma_mapa = _mapa_ubicable(raiz)
        if base_instalacion is not None and ubicacion.base != base_instalacion:
            raise ErrorGestor("El mapa de instalación cambió de raíz; prepara una migración explícita.")
        modo = "ubicable"
        carpeta = _comprobar_ubicacion(raiz, ubicacion)
        if lanzador and _clave_portable(ubicacion.base.split("/", 1)[0]) == LANZADOR:
            raise ErrorGestor(f"La raíz ubicable se solapa con la entrada del proyecto: {LANZADOR}.")
    retirados = sustitucion.inventariar(raiz, ubicacion, nuevo["huella_paquete"]) if reemplazar_anteriores else {}
    anterior, slot, agentes, modo_instalado = _estado(raiz, ubicacion)
    if activar_hook_solucion and CAPACIDAD_HOOK not in manifiesto["archivos"]:
        raise ErrorGestor("El paquete candidato carece del verificador para el hook de solución.")
    if modo is not None and modo_instalado is not None and modo != modo_instalado:
        raise ErrorGestor("El plan no puede cambiar el modo de una instalación reconocida.")
    modo = modo_instalado or modo or "estandar"
    entradas = ubicacion.entradas(modo, lanzador=lanzador)
    if modo != "estandar" and CAPACIDAD_AISLADA not in manifiesto["archivos"]:
        raise ErrorGestor(f"El paquete no admite el modo {modo}.")
    if ubicacion.ubicable:
        if CAPACIDAD_UBICABLE not in manifiesto["archivos"]:
            raise ErrorGestor("El paquete no admite la ubicación configurable.")
        _imagen_entrada(paquete, None)
    config = _compatibilidad(raiz)
    viejo = {} if slot is None else _validar_paquete(slot)["archivos"]
    navegacion_previa = NAVEGACION[0] in viejo
    lanzador_anterior = CAPACIDAD_LANZADOR in viejo
    if lanzador_anterior and not lanzador:
        raise ErrorGestor(f"Retirar el lanzador {LANZADOR} exige una migración propia.")
    if (anterior is not None and lanzador and not lanzador_anterior
            and _capturar(raiz, LANZADOR) is not None):
        raise ErrorGestor(f"Entrada sin procedencia compatible: {LANZADOR}")
    sdd_anterior = navegacion_previa and _anuncia_sdd(slot)
    if sdd_anterior and not sdd:
        raise ErrorGestor("Retirar las instrucciones SDD instaladas exige una migración propia.")
    migracion = anterior is not None and navegacion and not navegacion_previa
    if navegacion_previa and not navegacion:
        raise ErrorGestor("La retirada de la guía activa requiere una migración propia.")
    if navegacion_previa and not arranque and _admite_arranque(slot):
        raise ErrorGestor("Volver a un gestor que no reconozca el arranque de AGENTS requiere su propia migración.")
    if migracion and not migrar_navegacion:
        raise ErrorGestor("Usa el gestor candidato y --migrar-navegacion para esta transición.")
    if migrar_navegacion and not (migracion or (navegacion and anterior == nuevo)):
        raise ErrorGestor("La opción de transición requiere pasar de un slot histórico a uno con navegación.")
    if navegacion:
        guia = ubicacion.guia()
        _comprobar_guia(raiz, ubicacion, vacia=ubicacion.ubicable and anterior is None)
        if not navegacion_previa:
            for ruta in guia:
                if _capturar(raiz, ruta) is not None:
                    raise ErrorGestor(f"Guía de navegación sin procedencia compatible: {ruta}")
        entradas = {**entradas, **guia}
    if anterior is None:
        if accion == "actualizar":
            raise ErrorGestor("No existe una instalación reconocida para actualizar.")
        if modo == "estandar":
            _namespace(raiz, instalado=False)
        elif _puente_estandar(raiz, paquete):
            raise ErrorGestor("Hay un puente estándar sin procedencia reconocida.")
        for ruta in entradas:
            if _capturar(raiz, ruta) is not None:
                raise ErrorGestor(f"Entrada sin procedencia compatible: {ruta}")
        if ubicacion.ubicable and carpeta.exists():
            reservados = {"versiones", "transacciones"}
            if navegacion:
                reservados.add("skills")
            if any(nombre not in reservados and not re.fullmatch(r"preparacion-[a-f0-9]{32}", nombre)
                   for nombre in os.listdir(carpeta)):
                raise ErrorGestor("La raíz de instalación contiene archivos ajenos.")
    elif accion == "instalar" and anterior != nuevo:
        raise ErrorGestor("Ya hay otra versión instalada; prepara una actualización explícita.")
    if anterior is not None:
        if anterior["fuente_commit"] == nuevo["fuente_commit"] and anterior != nuevo:
            raise ErrorGestor("Una misma versión fuente no puede cambiar de identidad de paquete.")
        estables = [CAPACIDAD_UBICABLE] if ubicacion.ubicable else ENTRADAS.values()
        if migracion:
            # La transición reconoce las entradas anteriores mediante _estado y
            # actualiza el código autónomo que valida el nuevo inventario.
            estables = [] if ubicacion.ubicable else ["entradas/SKILL.md"]
            if ubicacion.ubicable and _imagen_entrada(slot, None) != _imagen_entrada(paquete, None):
                raise ErrorGestor("La transición de navegación conserva la skill operativa ubicable.")
        for entrada in estables:
            if viejo[entrada] != manifiesto["archivos"][entrada]:
                raise ErrorGestor("El paquete requiere modificar entradas estables; necesita acuerdo de migración.")
    contenido_agentes = _agentes(agentes, instalado=anterior is not None, modo=modo, ubicacion=ubicacion,
                                 navegacion=navegacion, arranque=arranque, migracion=migracion, publicar=True,
                                 sdd=sdd, sdd_anterior=sdd_anterior,
                                 lanzador=lanzador, lanzador_anterior=lanzador_anterior)
    cambia_agentes = agentes is None or _bytes(agentes) != contenido_agentes
    destino = _slot(raiz, nuevo, ubicacion, validar=False)
    if destino.exists() and _selector(_validar_paquete(destino)) != nuevo:
        raise ErrorGestor("El slot de destino contiene una versión incompatible.")
    if CAPACIDAD_HOOK in viejo and CAPACIDAD_HOOK not in manifiesto["archivos"] and _capturar(raiz, HOOK_SOLUCION) is not None:
        from .hook_solucion import gestionado

        if gestionado(raiz):
            raise ErrorGestor("El hook de solución activo requiere un paquete que conserve su ejecutor.")
    extras = _hook_solucion(raiz, ubicacion) if activar_hook_solucion else {}
    rutas_previstas = ubicacion.rutas(modo, navegacion, lanzador=lanzador) | extras.keys()
    firmas = {r: _firma(_capturar(raiz, r)) for r in sorted(rutas_previstas)}
    cambia_hook = any(firmas[r] != _firma(imagen) for r, imagen in extras.items())
    diff = [dict(ruta=r, tipo="alta" if r not in viejo else "baja" if r not in manifiesto["archivos"] else "modificacion",
                 anterior=viejo.get(r), nuevo=manifiesto["archivos"].get(r))
            for r in sorted(viejo.keys() | manifiesto["archivos"].keys()) if viejo.get(r) != manifiesto["archivos"].get(r)]
    plan = dict(schema=1, accion=accion, raiz=str(raiz), anterior=anterior, nuevo=nuevo, diff=diff,
                sin_cambios=anterior == nuevo and not cambia_agentes and not cambia_hook and not retirados,
                compatibilidad=manifiesto["compatibilidad"], precondiciones=firmas, config_consumidor=config,
                destinos=dict(version=ubicacion.version(nuevo), entradas=sorted(entradas.keys() | extras.keys()), agentes="AGENTS.md"))
    if modo != "estandar":
        plan["modo"] = modo
    if ubicacion.ubicable:
        plan.update(base_instalacion=ubicacion.base, mapa_instalacion=firma_mapa)
        plan["destinos"].update(selector=ubicacion.activo, diario=ubicacion.diario, bloqueo=ubicacion.bloqueo)
    if migracion:
        plan["migracion_navegacion"] = True
    if arranque and cambia_agentes:
        plan["antepone_arranque"] = True
    if activar_hook_solucion:
        plan.update(activar_hook_solucion=True, imagen_hook=_firma(extras[HOOK_SOLUCION]))
    if reemplazar_anteriores:
        plan.update(reemplazar_anteriores=True, retirados=retirados)
    if lanzador:
        plan["imagen_lanzador"] = _firma(_imagen_entrada(paquete, CAPACIDAD_LANZADOR))
    plan["huella_plan"] = _hash(plan)
    return plan


def planificar(raiz, paquete, *, accion="instalar", modo=None, base_instalacion=None, migrar_navegacion=False,
               reemplazar_anteriores=False, activar_hook_solucion=False):
    """Lectura estática de un paquete explícito y de las rutas gestionadas."""
    try:
        raiz = _raiz_repositorio(raiz)
        plan = _plan(raiz, paquete, accion, modo, base_instalacion=base_instalacion,
                     migrar_navegacion=migrar_navegacion, reemplazar_anteriores=reemplazar_anteriores,
                     activar_hook_solucion=activar_hook_solucion)
        return _salida("planificar", raiz=raiz, plan=plan)
    except Exception as exc:
        return _salida("planificar", exc, raiz=raiz)


def inspeccionar(raiz, *, base_instalacion=None):
    try:
        raiz = _raiz_repositorio(raiz)
        ubicacion = _CLASICA if base_instalacion is None else _Ubicacion(_base_ubicable(base_instalacion))
        if ubicacion.ubicable:
            _comprobar_ubicacion(raiz, ubicacion)
        activo, _, _, modo = _estado(raiz, ubicacion)
        datos_ubicacion = {"base_instalacion": ubicacion.base} if ubicacion.ubicable else {}
        return _salida("inspeccionar", raiz=raiz, instalado=activo is not None, activo=activo, modo=modo, **datos_ubicacion)
    except Exception as exc:
        return _salida("inspeccionar", exc, raiz=raiz)


def _bloquear(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise ErrorGestor("Otra operación mantiene el lock; conserva el estado y espera.") from exc


@contextmanager
def _lock(raiz, ubicacion):
    # Las operaciones de este gestor comparten checkout y AGENTS, incluso
    # cuando sus diarios y locks de compatibilidad viven en rutas distintas.
    directorio = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _bloquear(directorio)
        relativa = ubicacion.bloqueo
        _segura(raiz, relativa)
        with _padre(raiz, relativa, crear=True) as (padre, nombre):
            fd = os.open(nombre, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=padre)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ErrorGestor("El lock no es un archivo regular.")
                _bloquear(fd)
                yield
            finally:
                os.close(fd)
    finally:
        os.close(directorio)


def _sellar(diario):
    return dict(diario, huella_transaccion=_hash({k: v for k, v in diario.items() if k != "huella_transaccion"}))


def _validar_diario(diario, ubicacion):
    if (not isinstance(diario, dict) or type(diario.get("schema")) is not int or diario["schema"] != 1
            or not isinstance(diario.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", diario["id"])
            or diario.get("accion") not in {"instalar", "actualizar"} or diario.get("fase") not in FASES
            or diario.get("huella_transaccion") != _hash({k: v for k, v in diario.items() if k != "huella_transaccion"})):
        raise ErrorGestor("Diario pendiente inválido; no se adivina una recuperación.")
    if diario["anterior"] is not None: _selector_valido(diario["anterior"])
    _selector_valido(diario["nuevo"])
    modo = diario.get("modo", "estandar")
    modos = ("ubicable",) if ubicacion.ubicable else tuple(ENTRADAS_POR_MODO)
    base = ubicacion.base if ubicacion.ubicable else None
    migracion = diario.get("migracion_navegacion", False)
    activacion = diario.get("activar_hook_solucion", False)
    lanzador = diario.get("publica_lanzador", False)
    retirados = diario.get("retirados", {})
    sustitucion.validar_inventario(retirados, diario["nuevo"]["huella_paquete"])
    if (type(activacion) is not bool or type(lanzador) is not bool
            or ("retirados" in diario and diario["accion"] != "actualizar")
            or (diario["fase"] == "purga_confirmada" and not retirados)):
        raise ErrorGestor("El diario declara una sustitución o activación inválida.")
    if modo not in modos or diario.get("base_instalacion") != base or not isinstance(diario.get("rutas"), dict):
        raise ErrorGestor("El diario contiene destinos ajenos o carece de respaldos.")
    destinos = set(diario["rutas"])
    if activacion:
        if HOOK_SOLUCION not in destinos:
            raise ErrorGestor("Falta la imagen de activación del hook en el diario.")
        destinos.remove(HOOK_SOLUCION)
    navegacion = destinos == ubicacion.rutas(modo, True, lanzador=lanzador)
    if (not navegacion and destinos != ubicacion.rutas(modo, lanzador=lanzador)
            or type(migracion) is not bool
            or (migracion and (not navegacion or diario["accion"] != "actualizar" or diario["anterior"] is None))):
        raise ErrorGestor("El diario contiene destinos ajenos o carece de respaldos.")
    for ruta, imagenes in diario["rutas"].items():
        if not isinstance(imagenes, dict) or set(imagenes) != {"anterior", "nuevo"}:
            raise ErrorGestor("Imágenes del diario inválidas.")
        if imagenes["anterior"] is not None: _bytes(imagenes["anterior"])
        _bytes(imagenes["nuevo"])
        if ruta == LANZADOR and any(imagen is not None and imagen["permisos"] != 0o755
                                   for imagen in imagenes.values()):
            raise ErrorGestor(f"Permisos del lanzador inválidos en el diario: {ruta}.")
    if navegacion:
        esperado_ausente = migracion or diario["anterior"] is None
        if any((diario["rutas"][ruta]["anterior"] is None) != esperado_ausente for ruta in ubicacion.guia()):
            raise ErrorGestor("Los respaldos de navegación no corresponden a la transición.")
    return diario


def _guardar_diario(raiz, diario, ubicacion, *, exclusivo=False):
    diario = _sellar(diario)
    _escribir(raiz, ubicacion.diario, _imagen(_json(diario)), exclusivo=exclusivo)
    return diario


def _historia(raiz, diario, resultado_tx, ubicacion):
    final = _sellar(dict(diario, resultado=resultado_tx))
    nombre = "recuperacion.json" if resultado_tx == "recuperada" else "registro.json"
    ruta = ubicacion.transacciones + "/" + diario["id"] + "/" + nombre
    imagen = _imagen(_json(final))
    previa = _capturar(raiz, ruta)
    if previa is not None and previa != imagen:
        raise ErrorGestor("El histórico contiene otro registro; se conserva para revisión.")
    if previa is None: _escribir(raiz, ruta, imagen, exclusivo=True)
    _eliminar(raiz, ubicacion.diario)
    return final


def _rollback(raiz, diario, resultado_tx, ubicacion):
    _validar_diario(diario, ubicacion)
    if ubicacion.guia().keys() & diario["rutas"].keys():
        _comprobar_guia(raiz, ubicacion)
    for ruta, imagenes in diario["rutas"].items():
        actual = _capturar(raiz, ruta)
        if actual != imagenes["anterior"] and actual != imagenes["nuevo"]:
            raise ErrorGestor(f"Edición posterior o imagen desconocida en {ruta}; se preserva sin sobrescribir.")
    if diario.get("retirados"):
        sustitucion.restaurar(raiz, ubicacion.base, diario["id"], diario["retirados"])
    if diario["anterior"] is not None: _slot(raiz, diario["anterior"], ubicacion)
    # Restaurar selector primero desactiva la nueva versión antes de retirar puentes.
    for ruta in [ubicacion.activo, *sorted(diario["rutas"].keys() - {ubicacion.activo})]:
        imagenes = diario["rutas"][ruta]
        if _capturar(raiz, ruta) == imagenes["anterior"]: continue
        if imagenes["anterior"] is None: _eliminar(raiz, ruta)
        else: _escribir(raiz, ruta, imagenes["anterior"])
    return _historia(raiz, diario, resultado_tx, ubicacion)


def _finalizar_sustitucion(raiz, diario, ubicacion):
    _validar_diario(diario, ubicacion)
    _slot(raiz, diario["nuevo"], ubicacion)
    for ruta, imagenes in diario["rutas"].items():
        if _capturar(raiz, ruta) != imagenes["nuevo"]:
            raise ErrorGestor(f"La imagen publicada en {ruta} cambió; se conserva para revisión.")
    sustitucion.purgar(raiz, ubicacion.base, diario["id"], diario["retirados"])
    return _historia(raiz, diario, "aplicada", ubicacion)


def _copiar_slot(raiz, paquete, selector, ubicacion):
    destino = _slot(raiz, selector, ubicacion, validar=False)
    if destino.exists():
        _slot(raiz, selector, ubicacion)
        return
    manifiesto = _validar_paquete(paquete)
    preparacion = ubicacion.base + "/preparacion-" + uuid.uuid4().hex
    archivos_propios, directorios_propios = {}, {preparacion}
    with _padre(raiz, preparacion, crear=True) as (padre, nombre):
        os.mkdir(nombre, mode=0o755, dir_fd=padre)
        os.fsync(padre)
    try:
        for relativa in [*sorted(manifiesto["archivos"]), "manifiesto.json"]:
            imagen = _capturar(paquete, relativa)
            if imagen is None: raise ErrorGestor(f"El paquete cambió durante la copia: {relativa}")
            destino_relativo = preparacion + "/" + relativa
            archivos_propios[destino_relativo] = imagen
            for directorio in PurePosixPath(destino_relativo).parents:
                texto = directorio.as_posix()
                if texto.startswith(preparacion) and not _segura(raiz, texto).exists():
                    directorios_propios.add(texto)
            _escribir(raiz, destino_relativo, imagen, exclusivo=True)
        if _selector(_validar_paquete(raiz / preparacion)) != selector:
            raise ErrorGestor("El candidato completo no corresponde al selector previsto.")
        destino_relativo = ubicacion.version(selector)
        _segura(raiz, destino_relativo)
        with _padre(raiz, preparacion) as (origen_fd, origen_nombre), _padre(raiz, destino_relativo, crear=True) as (destino_fd, destino_nombre):
            try:
                os.stat(destino_nombre, dir_fd=destino_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ErrorGestor("El slot de destino apareció durante la copia; no se reemplaza.")
            os.rename(origen_nombre, destino_nombre, src_dir_fd=origen_fd, dst_dir_fd=destino_fd)
            os.fsync(origen_fd)
            os.fsync(destino_fd)
        _slot(raiz, selector, ubicacion)
    except Exception:
        # Retira únicamente imágenes propias todavía idénticas. No borra ajenos,
        # ni usa rmtree sobre directorios que puedan contener ediciones nuevas.
        for relativa, imagen in reversed(list(archivos_propios.items())):
            try:
                if _capturar(raiz, relativa) == imagen: _eliminar(raiz, relativa)
            except (ValueError, OSError):
                pass
        for relativa in sorted(directorios_propios, key=lambda p: len(PurePosixPath(p).parts), reverse=True):
            try:
                _segura(raiz, relativa)
                with _padre(raiz, relativa) as (padre, nombre):
                    os.rmdir(nombre, dir_fd=padre)
                    os.fsync(padre)
            except (ValueError, OSError):
                pass
        raise


def _repeticion(raiz, plan, actual, ubicacion):
    if (actual["nuevo"] != plan.get("nuevo") or not actual["sin_cambios"]
            or actual.get("modo") != plan.get("modo")
            or actual.get("mapa_instalacion") != plan.get("mapa_instalacion")
            or actual["config_consumidor"] != plan.get("config_consumidor")):
        return False
    carpeta = _segura(raiz, ubicacion.transacciones)
    if not carpeta.is_dir(): return False
    for directorio in carpeta.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", directorio.name): continue
        historia = ubicacion.transacciones + "/" + directorio.name
        relativa = historia + "/registro.json"
        diario = _leer_json(raiz, relativa)
        if diario is None: continue
        _validar_diario(diario, ubicacion)
        if (diario.get("resultado") == "aplicada" and diario.get("huella_plan") == plan["huella_plan"]
                and diario["nuevo"] == actual["nuevo"]
                and _capturar(raiz, historia + "/recuperacion.json") is None
                and all(_capturar(raiz, ruta) == imagenes["nuevo"] for ruta, imagenes in diario["rutas"].items())):
            return True
    return False


def aplicar(raiz, paquete, plan, *, base_instalacion=None):
    """Aplica un plan íntegro y publica su diario antes de cambiar el kit activo."""
    diario = None
    try:
        raiz = _raiz_repositorio(raiz)
        paquete = Path(paquete).absolute()
        if (not isinstance(plan, dict) or type(plan.get("schema")) is not int or plan["schema"] != 1
                or plan.get("huella_plan") != _hash({k: v for k, v in plan.items() if k != "huella_plan"})):
            raise ErrorGestor("Plan alterado o incompleto; prepara uno nuevo.")
        modo = plan.get("modo")
        base = plan.get("base_instalacion")
        if base_instalacion is not None and base != base_instalacion:
            raise ErrorGestor("El plan corresponde a otra ubicación.")
        ubicacion = _Ubicacion(_base_ubicable(base)) if modo == "ubicable" else _CLASICA
        migracion = plan.get("migracion_navegacion", False)
        extensiones = dict(migrar_navegacion=migracion,
                           reemplazar_anteriores=plan.get("reemplazar_anteriores", False),
                           activar_hook_solucion=plan.get("activar_hook_solucion", False))
        actual = _plan(raiz, paquete, plan.get("accion"), modo, base_instalacion=base, **extensiones)
        if actual != plan:
            if _repeticion(raiz, plan, actual, ubicacion):
                return _salida("aplicar", raiz=raiz, instalado=True, activo=actual["nuevo"], idempotente=True)
            raise ErrorGestor("El plan quedó obsoleto; revisa las diferencias y genera otro.")
        if plan["sin_cambios"]:
            return _salida("aplicar", raiz=raiz, instalado=True, activo=plan["nuevo"], idempotente=True)
        with _lock(raiz, ubicacion):
            if _plan(raiz, paquete, plan["accion"], modo, base_instalacion=base, **extensiones) != plan:
                raise ErrorGestor("Las precondiciones cambiaron al tomar el lock.")
            _copiar_slot(raiz, paquete, plan["nuevo"], ubicacion)
            slot = _slot(raiz, plan["nuevo"], ubicacion)
            if ubicacion.ubicable:
                if _firma(_capturar(raiz, MAPA_UBICABLE)) != plan["mapa_instalacion"]:
                    raise ErrorGestor("El mapa cambió antes de publicar.")
            rutas = {}
            lanzador = (slot / CAPACIDAD_LANZADOR).is_file()
            entradas = ubicacion.entradas(modo or "estandar", lanzador=lanzador)
            navegacion = (slot / NAVEGACION[0]).is_file()
            guia = ubicacion.guia() if navegacion else {}
            if guia:
                _comprobar_guia(raiz, ubicacion, vacia=ubicacion.ubicable and plan["anterior"] is None)
                entradas = {**entradas, **guia}
            for ruta, entrada in entradas.items():
                rutas[ruta] = dict(anterior=_capturar(raiz, ruta), nuevo=_imagen_entrada(slot, entrada))
            if lanzador and _firma(rutas[LANZADOR]["nuevo"]) != plan.get("imagen_lanzador"):
                raise ErrorGestor(f"La imagen aprobada del lanzador cambió: {LANZADOR}.")
            extras = _hook_solucion(raiz, ubicacion) if extensiones["activar_hook_solucion"] else {}
            for ruta, imagen in extras.items():
                if _firma(imagen) != plan.get("imagen_hook"):
                    raise ErrorGestor("La imagen aprobada del hook cambió antes de publicar.")
                rutas[ruta] = dict(anterior=_capturar(raiz, ruta), nuevo=imagen)
            agentes = _capturar(raiz, "AGENTS.md")
            previo = _slot(raiz, plan["anterior"], ubicacion) if plan["anterior"] is not None else None
            contenido = _agentes(agentes, instalado=plan["anterior"] is not None, modo=modo or "estandar",
                                 ubicacion=ubicacion, navegacion=navegacion,
                                 arranque=navegacion and _admite_arranque(slot), migracion=migracion, publicar=True,
                                 sdd=navegacion and _anuncia_sdd(slot),
                                 sdd_anterior=previo is not None and (previo / NAVEGACION[0]).is_file()
                                 and _anuncia_sdd(previo), lanzador=lanzador,
                                 lanzador_anterior=previo is not None and (previo / CAPACIDAD_LANZADOR).is_file())
            rutas["AGENTS.md"] = dict(anterior=agentes, nuevo=_imagen(contenido, 0o644 if agentes is None else agentes["permisos"]))
            activo = ubicacion.activo
            rutas[activo] = dict(anterior=_capturar(raiz, activo), nuevo=_imagen(_json(plan["nuevo"])))
            if any(_firma(imagenes["anterior"]) != plan["precondiciones"][ruta]
                   for ruta, imagenes in rutas.items()):
                raise ErrorGestor("Una entrada gestionada cambió antes de publicar.")
            diario = dict(schema=1, id=uuid.uuid4().hex, accion=plan["accion"], anterior=plan["anterior"], nuevo=plan["nuevo"],
                          fase="preparado", huella_plan=plan["huella_plan"], rutas=rutas)
            if modo is not None:
                diario["modo"] = modo
            if ubicacion.ubicable:
                diario.update(base_instalacion=base, mapa_instalacion=plan["mapa_instalacion"])
            if migracion:
                diario["migracion_navegacion"] = True
            if extras:
                diario["activar_hook_solucion"] = True
            if lanzador:
                diario["publica_lanzador"] = True
            if plan.get("retirados"):
                diario["retirados"] = plan["retirados"]
            diario = _guardar_diario(raiz, diario, ubicacion, exclusivo=True)
            try:
                _punto("diario_preparado")
                diario = _guardar_diario(raiz, dict(diario, fase="version_lista"), ubicacion)
                _punto("version_lista")
                for ruta in [*entradas, "AGENTS.md", *extras]:
                    if ruta in guia:
                        _comprobar_guia(raiz, ubicacion)
                    imagenes = rutas[ruta]
                    if _capturar(raiz, ruta) != imagenes["anterior"]:
                        raise ErrorGestor(f"La entrada cambió antes de publicar: {ruta}")
                    if imagenes["anterior"] != imagenes["nuevo"]:
                        _escribir(raiz, ruta, imagenes["nuevo"], exclusivo=imagenes["anterior"] is None)
                    _punto("entrada_publicada:" + ruta)
                diario = _guardar_diario(raiz, dict(diario, fase="entradas_publicadas"), ubicacion)
                _punto("entradas_publicadas")
                _punto("antes_selector")
                if guia:
                    _comprobar_guia(raiz, ubicacion)
                if _capturar(raiz, activo) != rutas[activo]["anterior"]:
                    raise ErrorGestor("El selector cambió antes de publicar.")
                _slot(raiz, plan["nuevo"], ubicacion)
                _escribir(raiz, activo, rutas[activo]["nuevo"], exclusivo=rutas[activo]["anterior"] is None)
                diario = _guardar_diario(raiz, dict(diario, fase="selector_publicado"), ubicacion)
                _punto("selector_publicado")
                _punto("antes_finalizar")
                if diario.get("retirados"):
                    sustitucion.apartar(raiz, ubicacion.base, diario["id"], diario["retirados"])
                    _punto("slots_apartados")
                    diario = _guardar_diario(raiz, dict(diario, fase="purga_confirmada"), ubicacion)
                    _punto("purga_confirmada")
                    _finalizar_sustitucion(raiz, diario, ubicacion)
                else:
                    _historia(raiz, diario, "aplicada", ubicacion)
            except Exception:
                persistido = _leer_json(raiz, ubicacion.diario)
                if persistido is not None and persistido["fase"] != "purga_confirmada":
                    _rollback(raiz, persistido, "revertida", ubicacion)
                raise
        return _salida("aplicar", raiz=raiz, instalado=True, activo=plan["nuevo"], idempotente=False, transaccion=diario["id"])
    except Exception as exc:
        return _salida("aplicar", exc, raiz=raiz)


def recuperar(raiz, *, base_instalacion=None):
    """Restaura o completa una transacción pendiente según la decisión guardada."""
    try:
        raiz = _raiz_repositorio(raiz)
        if base_instalacion is None and _capturar(raiz, DIARIO_UBICABLE) is not None:
            if _capturar(raiz, DIARIO) is not None:
                raise ErrorGestor("Hay diarios simultáneos de dos modos; conserva ambos para revisión.")
            pendiente = _leer_json(raiz, DIARIO_UBICABLE)
            base_instalacion = _base_ubicable(pendiente["base_instalacion"])
        ubicacion = _CLASICA if base_instalacion is None else _Ubicacion(_base_ubicable(base_instalacion))
        if ubicacion.ubicable:
            _comprobar_ubicacion(raiz, ubicacion)
        if _capturar(raiz, ubicacion.diario) is None:
            activo, _, _, _ = _estado(raiz, ubicacion)
            return _salida("recuperar", raiz=raiz, recuperado=False, idempotente=True, activo=activo, instalado=activo is not None)
        with _lock(raiz, ubicacion):
            imagen_diario = _capturar(raiz, ubicacion.diario)
            if imagen_diario is None:
                activo, _, _, _ = _estado(raiz, ubicacion)
                return _salida("recuperar", raiz=raiz, recuperado=False, idempotente=True, activo=activo, instalado=activo is not None)
            diario = json_estricto(_bytes(imagen_diario).decode("utf-8"))
            if diario.get("fase") == "purga_confirmada":
                _finalizar_sustitucion(raiz, diario, ubicacion)
                activo = diario["nuevo"]
            else:
                _rollback(raiz, diario, "recuperada", ubicacion)
                activo = diario["anterior"]
        return _salida("recuperar", raiz=raiz, recuperado=True, idempotente=False,
                       activo=activo, instalado=activo is not None)
    except Exception as exc:
        return _salida("recuperar", exc, raiz=raiz)
