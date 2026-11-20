"""Selección explícita del perfil nativo y procedencia de sus fuentes Git."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import posixpath
import re

from .arboles import ErrorArbol, LectorArbol, _git, _leer_trabajo, _raiz_repositorio, _ruta, commit_lectura
from .documentos import json_estricto
from .modelo import coincide, diagnostico, resultado


PERFIL = "heimdall-v2"
PROYECTO = "heimdall"
PIN = "0e3f6308a67fdb21d45fa0570975029fab2d9380"
CONFIG = "gobernanza/config.json"
TAXONOMIA = "gobernanza/taxonomy/projects/"
RAICES = {"G": "gobernanza/sesiones", "S": "sesiones"}
LANZADOR_RAIZ = "gobernanza-kit"
FOLIO = r"[GS][0-9]{2}-[0-9]{2}"
FICHA = r"F-[0-9]{4}"
OID = r"(?:[a-f0-9]{40}|[a-f0-9]{64})"
ACTOR = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
RAMA = rf"codex/({FOLIO}|PLANIFICACION)/({ACTOR})"


class ErrorConvivencia(ValueError):
    def __init__(self, mensaje, ruta=CONFIG, codigo="FUENTE_NATIVA"):
        super().__init__(f"{ruta}: {mensaje}")
        self.mensaje = mensaje
        self.ruta = ruta
        self.codigo = codigo


def informe_error(operacion, exc):
    ruta = getattr(exc, "ruta", CONFIG)
    codigo = getattr(exc, "codigo", "ARBOL_NATIVO")
    return resultado(operacion, [
        diagnostico(codigo, ruta, "Selección y fuentes nativas cotejadas", str(exc),
                    "Comprueba el árbol, el perfil guardado y las fuentes canónicas citadas."),
    ])


def huella_bytes(contenido):
    return hashlib.sha256(contenido).hexdigest()


def huella_datos(datos):
    return huella_bytes(json.dumps(datos, sort_keys=True, separators=(",", ":")).encode())


def objeto(datos, ruta):
    try:
        valor = json_estricto(datos.decode("utf-8"))
        if not isinstance(valor, dict):
            raise ValueError("se requiere un objeto JSON")
    except (UnicodeError, ValueError) as exc:
        raise ErrorConvivencia(str(exc), ruta) from exc
    return valor


def frontal(texto, ruta):
    lineas = texto.splitlines()
    try:
        if not lineas or lineas[0] != "---":
            raise ValueError("falta el bloque JSON inicial")
        fin = lineas.index("---", 1)
    except ValueError as exc:
        raise ErrorConvivencia(str(exc), ruta) from exc
    return objeto("\n".join(lineas[1:fin]).encode("utf-8"), ruta), "\n".join(lineas[fin + 1:])


def campo(texto, nombre):
    patron = rf"^\*\*{re.escape(nombre)}:\*\*\s*([^\r\n]+)"
    valor = re.search(patron, texto, re.MULTILINE)
    return valor.group(1).strip().strip("`") if valor else None


def _secciones(texto):
    titulos = tuple(re.finditer(r"^##\s+(\d+)\.(?:\s+|$)(.*)$", texto, re.MULTILINE))
    return [(int(titulo[1]), titulo[2], texto[titulo.end():titulos[i + 1].start()]
             if i + 1 < len(titulos) else texto[titulo.end():])
            for i, titulo in enumerate(titulos)]


def contratos_en(texto, ruta):
    """Resuelve citas de spec y enmienda escritas como ruta o enlace Markdown."""
    patron = r"(?:gobernanza/)?sdd/(?:spec_|enmienda_)[^/`\s]+\.md"
    destinos = re.findall(rf"`({patron})`", texto)
    for enlace in re.findall(r"\]\(([^)\s]+)\)", texto):
        relativo = enlace.split("#", 1)[0]
        if (not relativo or relativo.startswith("/") or any(c in relativo for c in "?:%\\")
                or not re.fullmatch(r"(?:spec_|enmienda_)[^/]+\.md", posixpath.basename(relativo))):
            continue
        resuelto = posixpath.normpath(posixpath.join(posixpath.dirname(ruta), relativo))
        destinos.append(_ruta(resuelto))
    return list(dict.fromkeys(destinos))


def _en_ruta_dominio(ruta, dominio, raices_solucion):
    origen = ruta.split("/", 1)[0]
    if origen == LANZADOR_RAIZ:
        return dominio == "G" and ruta == LANZADOR_RAIZ
    if dominio == "G":
        return origen in {"gobernanza", ".codex", ".claude", ".githooks", "AGENTS.md", ".gitignore"}
    return origen in {"sdd", "sesiones", *raices_solucion}


def _patron(texto, dominio, raices_solucion, ruta):
    limpio = texto.removeprefix("repo:").rstrip("/")
    try:
        _ruta(limpio)
    except ErrorArbol as exc:
        raise ErrorConvivencia(str(exc), ruta) from exc
    if limpio == LANZADOR_RAIZ and texto.endswith("/"):
        raise ErrorConvivencia(f"El lanzador de raíz debe declararse como archivo: {texto}.", ruta)
    if not _en_ruta_dominio(limpio, dominio, raices_solucion):
        # El pin contempla estas zonas para operación local G; los lotes
        # versionables siguen exigiendo dominio y nunca las reciben.
        if not (dominio == "G" and re.match(
                r"^\.heimdall/runtime/(?:motor|feature-handoffs|feature-validations)(?:/|$)|"
                r"^\.heimdall/runtime/gobernanza-kit\.json$", limpio)):
            raise ErrorConvivencia(f"Destino fuera del dominio {dominio}: {texto}.", ruta)
    return limpio + ("/" if texto.endswith("/") else "")


def cubre_ruta(patron, ruta):
    return coincide(ruta, patron) or ruta == patron.rstrip("/")


def _config(lector):
    try:
        entrada = lector.entrada(CONFIG)
    except ErrorArbol as exc:
        raise ErrorConvivencia(str(exc)) from exc
    return objeto(entrada[1], CONFIG) if entrada else {}


def _declara(config):
    if "perfil_operacion" not in config:
        return None
    perfil = config["perfil_operacion"]
    if (perfil != PERFIL or type(config.get("schema")) is not int or config["schema"] != 1
            or config.get("proyecto") != PROYECTO):
        raise ErrorConvivencia(f"Perfil, esquema o proyecto desconocido: {perfil!r}.", codigo="PERFIL_INVALIDO")
    return perfil


def seleccionar_perfil(raiz, arbol="worktree", *, historico=False, requiere_nativo=False):
    """Selecciona perfil antes de cualquier efecto. None conserva el despacho r1."""
    if not isinstance(arbol, str) or not arbol:
        raise ErrorConvivencia("Selecciona worktree, staged o una ref Git literal.")
    if historico and arbol in {"worktree", "staged"}:
        raise ErrorConvivencia("Una consulta histórica requiere un commit o ref Git.")
    carpeta = Path(raiz).resolve(strict=True)
    # Fuera de Git se conserva la consulta documental r1.
    if not (carpeta / ".git").exists():
        try:
            entrada = _leer_trabajo(carpeta, CONFIG)
            config = objeto(entrada[1], CONFIG) if entrada and entrada[0] != "120000" else {}
        except (ErrorConvivencia, ErrorArbol):
            if requiere_nativo or arbol != "worktree":
                raise
            return None
        if requiere_nativo or arbol != "worktree" or _declara(config):
            raise ErrorConvivencia("El perfil exige la raíz Git explícita.")
        return None
    carpeta = _raiz_repositorio(carpeta)
    if historico:
        elegido = LectorArbol(carpeta, arbol)
        config = _config(elegido)
        if _declara(config) is None:
            if requiere_nativo:
                raise ErrorConvivencia("La configuración histórica no declara el perfil nativo.")
            return None
        return RepositorioNativo(carpeta, elegido, config, historico=True)
    # Primero sondear sólo la configuración para no aplicar el inventario
    # global nativo a repos r1. En un árbol nativo se validan luego las entradas.
    try:
        cabeza = commit_lectura(carpeta, "HEAD")
    except ErrorArbol:
        rama = _git(carpeta, "branch", "--show-current").decode("utf-8").strip()
        if (not rama or _git(carpeta, "for-each-ref", "--format=%(refname)", f"refs/heads/{rama}")
                or arbol not in {"worktree", "staged"}):
            raise
        staged = _declara(_config_seleccion(carpeta, None, "staged"))
        trabajo = _declara(_config_seleccion(carpeta, None, "worktree"))
        if requiere_nativo or staged or trabajo:
            raise ErrorConvivencia("El opt-in requiere una configuración guardada en HEAD.", codigo="PERFIL_REQUERIDO")
        return None
    opciones = dict.fromkeys(("HEAD", "staged", "worktree", arbol))
    try:
        datos = {nombre: _config_seleccion(carpeta, cabeza, nombre) for nombre in opciones}
    except ErrorArbol as exc:
        raise ErrorConvivencia(str(exc)) from exc
    perfiles = {nombre: _declara(config) for nombre, config in datos.items()}
    if len(set(perfiles.values())) != 1:
        cambios = ", ".join(f"{nombre}={perfil!r}" for nombre, perfil in perfiles.items())
        raise ErrorConvivencia(f"Deriva de selección de perfil ({cambios}).", codigo="PERFIL_DERIVA")
    if perfiles["HEAD"] is None:
        if requiere_nativo:
            raise ErrorConvivencia("La opción solicitada exige heimdall-v2 guardado.", codigo="PERFIL_REQUERIDO")
        return None
    elegido = LectorArbol(carpeta, cabeza if arbol == "HEAD" else arbol)
    config = _config(elegido)
    if config != datos[arbol] or commit_lectura(carpeta, "HEAD") != cabeza:
        raise ErrorConvivencia("Cambió el árbol durante la selección.", codigo="PERFIL_DERIVA")
    return RepositorioNativo(carpeta, elegido, config, historico=False, head=cabeza)


def _config_seleccion(raiz, head, arbol):
    """Lee sólo el destino declarado; nunca hace checkout ni invoca filtros."""
    if arbol == "worktree":
        entrada = _leer_trabajo(raiz, CONFIG)
        if entrada is None or entrada[0] != "120000":
            return objeto(entrada[1], CONFIG) if entrada else {}
        raise ErrorArbol(f"Configuración enlazada: {CONFIG}.")
    if arbol == "staged":
        registros = _git(raiz, "ls-files", "--stage", "-z", "--", CONFIG)
        if not registros:
            return {}
        filas = registros.rstrip(b"\0").split(b"\0")
        if len(filas) != 1:
            raise ErrorArbol(f"Configuración en conflicto: {CONFIG}.")
        cabecera, _ = filas[0].split(b"\t", 1)
        modo, oid, etapa = cabecera.decode("ascii").split()
        if modo not in ("100644", "100755") or etapa != "0":
            raise ErrorArbol(f"Configuración staged insegura: {CONFIG}.")
    else:
        ref = head if arbol == "HEAD" else commit_lectura(raiz, arbol)
        registros = _git(raiz, "ls-tree", "-z", "--full-tree", ref, "--", CONFIG)
        if not registros:
            # Un ancestro enlazado no debe pasar por ausencia de opt-in.
            padre = _git(raiz, "ls-tree", "-z", "--full-tree", ref, "--", "gobernanza")
            if padre and not padre.startswith(b"040000 tree "):
                raise ErrorArbol("El directorio de configuración no es un árbol regular.")
            return {}
        cabecera, _ = registros.rstrip(b"\0").split(b"\t", 1)
        modo, tipo, oid = cabecera.decode("ascii").split()
        if modo not in ("100644", "100755") or tipo != "blob":
            raise ErrorArbol(f"Configuración Git insegura: {CONFIG}.")
    return objeto(_git(raiz, "cat-file", "blob", oid), CONFIG)


@dataclass(frozen=True)
class Fuente:
    ruta: str
    blob: str
    ref: str | None
    sha256: str


class RepositorioNativo:
    perfil = PERFIL
    proyecto = PROYECTO

    def __init__(self, raiz, lector, config, *, historico, head=None):
        self.raiz = raiz
        self.lector = lector
        self.arbol = lector.arbol
        self.commit = lector.commit
        self.config = config
        self.historico = historico
        self.head = head or commit_lectura(raiz, "HEAD")
        self._lector_head = None
        self._historicos = {}
        self.rama = _git(raiz, "branch", "--show-current").decode().strip() or None
        comun = _git(raiz, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.comun = Path(comun.decode().rstrip("\n")).resolve(strict=True)
        pin = objeto(self.leer("gobernanza/motor.lock"), "gobernanza/motor.lock")
        if (pin.get("revision") != PIN or pin.get("project_id") != self.proyecto
                or type(pin.get("schema_version")) is not int or pin["schema_version"] != 1
                or not isinstance(pin.get("files"), dict)):
            raise ErrorConvivencia("El proyecto o revisión del pin no es el cotejado por H2.",
                                   "gobernanza/motor.lock", "PIN_DISCREPANCIA")
        ruta_indice = TAXONOMIA + "index.md"
        indice, _ = frontal(self.texto(ruta_indice), ruta_indice)
        proyectos = indice.get("projects")
        if (indice.get("schema_version") != 2 or not isinstance(proyectos, dict)
                or not isinstance(proyectos.get(self.proyecto, proyectos.get("$PROJECT_ID")), str)):
            raise ErrorConvivencia("La taxonomía no identifica el perfil del proyecto.", ruta_indice)
        archivo = proyectos.get(self.proyecto, proyectos.get("$PROJECT_ID"))
        if not re.fullmatch(r"[\w.-]+\.md", archivo):
            raise ErrorConvivencia("Ruta de perfil no canónica.", ruta_indice)
        self.ruta_perfil = TAXONOMIA + archivo
        self.taxonomia, _ = frontal(self.texto(self.ruta_perfil), self.ruta_perfil)
        continuidad = {
            "gobernanza": {"path": RAICES["G"], "plan_glob": "historial/G*.md"},
            "funcional": {"path": RAICES["S"], "plan_glob": "historial/S*.md"},
        }
        if (self.taxonomia.get("profile_version") != 2 or self.taxonomia.get("schema_version") != 2
                or self.taxonomia.get("project_id") not in (self.proyecto, "$PROJECT_ID")
                or self.taxonomia.get("continuity") != continuidad):
            raise ErrorConvivencia("Raíces, proyecto o versión del perfil nativo incompatibles.", self.ruta_perfil)
        self.perfil_hash = huella_datos(self.taxonomia)
        raices_solucion = self.taxonomia.get("solution_roots", ["solucion"])
        if (not isinstance(raices_solucion, list)
                or any(not isinstance(r, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", r)
                       or r in {"gobernanza", "sdd", "sesiones", LANZADOR_RAIZ} for r in raices_solucion)):
            raise ErrorConvivencia("Raíces de solución del perfil incompatibles.", self.ruta_perfil)
        self.raices_solucion = {"solucion", *raices_solucion}

    def leer(self, ruta):
        try:
            return self.lector.leer(ruta)
        except ErrorArbol as exc:
            raise ErrorConvivencia(str(exc), ruta) from exc

    def texto(self, ruta):
        try:
            return self.leer(ruta).decode("utf-8")
        except UnicodeError as exc:
            raise ErrorConvivencia("La fuente debe estar en UTF-8.", ruta) from exc

    def listar(self, prefijo=""):
        return self.lector.listar(prefijo)

    def fuente(self, ruta):
        contenido = self.leer(ruta)
        blob = self.lector.blob(ruta, contenido, longitud=len(self.head))
        ref = self.commit
        if ref is None:
            if self._lector_head is None:
                self._lector_head = LectorArbol(self.raiz, self.head)
            entrada = self._lector_head.entradas.get(ruta)
            if entrada and entrada[1] == blob:
                ref = self.head
        return Fuente(ruta, blob, ref, huella_bytes(contenido))

    def en_arbol(self, arbol, *, historico=False):
        if not historico:
            return seleccionar_perfil(self.raiz, arbol, requiere_nativo=True)
        if arbol in ("worktree", "staged"):
            raise ErrorConvivencia("La procedencia histórica requiere una ref Git.")
        sha = arbol if isinstance(arbol, str) and re.fullmatch(OID, arbol) else self.commit_ref(arbol)
        if sha not in self._historicos:
            lector = LectorArbol(self.raiz, sha)
            config = _config(lector)
            _declara(config)
            self._historicos[sha] = RepositorioNativo(
                self.raiz, lector, config or self.config, historico=True, head=self.head,
            )
        return self._historicos[sha]

    def commit_ref(self, ref):
        return commit_lectura(self.raiz, ref)

    def git(self, *args):
        if not args or args[0] not in {
            "rev-parse", "rev-list", "ls-files", "ls-tree", "merge-base",
            "for-each-ref", "cat-file", "diff-tree", "log", "check-ignore",
        } and args not in {
            ("branch", "--show-current"),
            ("symbolic-ref", "--quiet", "HEAD"),
            ("worktree", "list", "--porcelain", "-z"),
        }:
            raise ErrorConvivencia("Operación fuera del lector Git nativo.")
        limites = {"--output", "--ext-diff", "--textconv", "--filters", "--show-signature"}
        if any(not isinstance(opcion, str) or opcion.split("=", 1)[0] in limites for opcion in args):
            raise ErrorConvivencia("La lectura de Git excluye efectos y ejecución de helpers.")
        if args[0] == "log":
            args = ("log", "--no-ext-diff", "--no-textconv", "--no-show-signature", *args[1:])
        return _git(self.raiz, *args)

    def runtime(self, ruta):
        nombre = _ruta(ruta)
        if not nombre.startswith(f".{self.proyecto}/runtime/"):
            raise ErrorConvivencia("Destino ajeno al runtime nativo.", ruta)
        imagen = _leer_trabajo(self.raiz, nombre)
        if imagen is not None and imagen[0] not in ("100644", "100755"):
            raise ErrorConvivencia("Registro runtime enlazado.", ruta)
        return objeto(imagen[1], nombre) if imagen else None

    def rutas_planes(self):
        rutas = []
        for dominio, raiz in RAICES.items():
            prefijo = raiz + "/historial/"
            for ruta in self.listar(prefijo):
                nombre = ruta.removeprefix(prefijo)
                if not re.fullmatch(rf"({FOLIO})(?:_[^/]+)?\.md", nombre):
                    continue
                if nombre[0] != dominio:
                    raise ErrorConvivencia("Plan fuera de la continuidad de su dominio.", ruta, "DOMINIO_NATIVO")
                try:
                    if self.lector.entrada(ruta) is not None:
                        rutas.append((nombre[:6], ruta))
                except ErrorArbol as exc:
                    raise ErrorConvivencia(str(exc), ruta) from exc
        return rutas

    def comprobar_activos(self, candidatos):
        activos = {}
        for folio, ruta in candidatos:
            if campo(self.texto(ruta), "Estado") != "Activo":
                continue
            dominio = folio[0]
            if dominio in activos:
                raise ErrorConvivencia(f"Dos planes Activos del dominio: {activos[dominio]} y {ruta}.",
                                       ruta, "PLAN_DUPLICADO")
            activos[dominio] = ruta
        return activos

    def plan(self, folio):
        if not isinstance(folio, str) or re.fullmatch(FOLIO, folio) is None:
            raise ErrorConvivencia(f"Folio G/S inválido: {folio!r}.")
        rutas = self.rutas_planes()
        candidatos = [ruta for nombre, ruta in rutas if nombre == folio]
        if len(candidatos) != 1:
            raise ErrorConvivencia(f"Se requiere un plan canónico para {folio}: {candidatos}.",
                                   RAICES[folio[0]], "PLAN_CANONICO")
        self.comprobar_activos(rutas)
        return self._plan(folio, candidatos[0])

    def _plan(self, folio, ruta):
        texto = self.texto(ruta)
        dominio = folio[0]
        raiz = RAICES[dominio]
        cabecera = texto.split("\n##", 1)[0]
        if not re.search(rf"^# .*\b{folio}\b", cabecera, re.MULTILINE):
            raise ErrorConvivencia(f"La cabecera no identifica {folio}.", ruta)
        proyecto, perfil = campo(cabecera, "Proyecto"), campo(cabecera, "Perfil versión")
        modulo, version = campo(cabecera, "Módulo"), campo(cabecera, "Versión")
        estado, evidencia = campo(cabecera, "Estado"), campo(cabecera, "Evidencia")
        if (proyecto != self.proyecto or perfil != "2" or not re.fullmatch(r"[a-z0-9-]+", modulo or "")
                or not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", version or "")
                or estado not in {"Borrador", "Activo", "Completado", "Cancelado", "Descartado"}):
            raise ErrorConvivencia("Cabecera, perfil, versión o módulo del plan inválido.", ruta)
        prefijo_modulo = f"{raiz}/modulos/{modulo}/"
        if (not evidencia or re.fullmatch(re.escape(prefijo_modulo) + r"sesiones/[^/]+\.md", evidencia) is None):
            raise ErrorConvivencia("La evidencia primaria no corresponde al módulo y dominio del plan.", ruta)
        continuidad, estado_modulo = raiz + "/continuidad.md", prefijo_modulo + "estado.md"
        spec_base = "gobernanza/sdd/" if dominio == "G" else "sdd/"
        spec = spec_base + "spec_" + modulo + ".md"
        try:
            tablas = self.texto(spec)
        except ErrorConvivencia as exc:
            raise ErrorConvivencia(f"El módulo {modulo} requiere su spec {spec}: {exc.mensaje}", ruta) from exc
        if (not etiqueta(tablas, "Módulo", modulo) or not etiqueta(tablas, "Proyecto", proyecto)):
            raise ErrorConvivencia(f"Identidad de módulo o proyecto incompatible con {ruta}.", spec)
        if not re.search(rf"`{re.escape(modulo)}`|modulos/{re.escape(modulo)}/", self.texto(continuidad)):
            raise ErrorConvivencia(f"La continuidad no enruta el módulo de {ruta}.", continuidad)
        self.leer(estado_modulo)
        self.leer(evidencia)
        secciones = _secciones(texto)
        seccion3 = [contenido for numero, _, contenido in secciones if numero == 3]
        if len(seccion3) != 1:
            raise ErrorConvivencia("Se requiere una sección §3 de alcance única.", ruta)
        destinos = re.findall(r"`([^`\n]+)`", seccion3[0])
        alcance = list(dict.fromkeys(_patron(p, dominio, self.raices_solucion, ruta) for p in destinos))
        for destino in alcance:
            estatico = re.split(r"[*?\[]", destino, maxsplit=1)[0].rstrip("/")
            if estatico:
                try:
                    self.lector.comprobar_ruta(estatico)
                except ErrorArbol as exc:
                    raise ErrorConvivencia(str(exc), destino) from exc
        if not alcance:
            raise ErrorConvivencia("La sección §3 no enumera destinos.", ruta)
        referencias_tecnicas = "\n".join(contenido for numero, _, contenido in secciones if numero == 2)
        contratos = contratos_en(referencias_tecnicas, ruta)
        if spec not in contratos or any(not contrato.startswith(spec_base) for contrato in contratos):
            raise ErrorConvivencia("El contrato técnico cruza dominios o no cita el spec primario.", ruta)
        for contrato in contratos:
            self.leer(contrato)
        ficha_declarada = campo(cabecera, "Funcionalidades") or ""
        funcionalidades = [ref.strip().strip("`") for ref in ficha_declarada.split(",") if ref.strip()]
        for ref in funcionalidades:
            ficha = self.ficha(ref)
            if dominio != "S" or ficha["modulo"] != modulo:
                raise ErrorConvivencia(f"Ficha fuera del módulo o dominio: {ref}.", ruta)
        aprobaciones = _aprobaciones(cabecera, secciones, folio, version)
        actual = aprobaciones.get(version, {})
        fuente = self.fuente(ruta)
        transaccion = campo(cabecera, "ID de sesión")
        rama = re.fullmatch(RAMA, self.rama or "")
        if transaccion is None and rama and rama[1] == folio:
            transaccion = rama[2]
        return {
            "schema": 1, "folio": folio, "dominio": dominio, "proyecto": proyecto,
            "perfil": self.perfil, "modulo": modulo, "version": version, "estado": estado,
            "ruta": ruta, "evidencia": evidencia, "continuidad": continuidad,
            "estado_modulo": estado_modulo, "alcance": alcance, "contratos": contratos,
            "funcionalidades": funcionalidades, "ref": fuente.ref, "blob": fuente.blob,
            "sha256": fuente.sha256, "base": actual.get("base"), "cita": actual.get("cita"),
            "aprobaciones": list(aprobaciones.values()), "transaccion": transaccion,
        }

    def ficha(self, ref):
        match = re.fullmatch(rf"({FICHA})(?:@r([1-9][0-9]*))?", ref) if isinstance(ref, str) else None
        if not match:
            raise ErrorConvivencia(f"Identidad de ficha inválida: {ref!r}.", "sdd/funcionalidades")
        prefijo = "sdd/funcionalidades/" + match[1]
        candidatas = [ruta for ruta in self.listar(prefijo)
                      if re.fullmatch(re.escape(prefijo) + r"(?:_[^/]+)?\.md", ruta)]
        if len(candidatas) != 1:
            raise ErrorConvivencia(f"Se requiere una ficha canónica para {ref}: {candidatas}.", prefijo)
        ruta = candidatas[0]
        datos, _ = frontal(self.texto(ruta), ruta)
        revisiones = datos.get("revisiones")
        modulo = datos.get("modulo")
        if (datos.get("id") != match[1] or not isinstance(modulo, str) or not re.fullmatch(r"[a-z0-9-]+", modulo)
                or datos.get("estado") not in {"Borrador", "Validado", "Archivado", "Deprecado"}
                or not isinstance(revisiones, list) or not revisiones
                or any(not isinstance(r, dict) or type(r.get("revision")) is not int or r["revision"] < 1
                       or not isinstance(r.get("criterios"), dict)
                       or any(not re.fullmatch(r"C[0-9]{2}", k) or not isinstance(v, str) or not v.strip()
                              for k, v in r["criterios"].items()) for r in revisiones)):
            raise ErrorConvivencia("Identidad o revisiones de ficha inconsistentes.", ruta)
        vigentes = {r["revision"]: r["criterios"] for r in revisiones}
        revision = int(match[2]) if match[2] else max(vigentes)
        if len(vigentes) != len(revisiones) or revision not in vigentes:
            raise ErrorConvivencia(f"Revisión ausente o ambigua: {ref}.", ruta)
        rutas = datos.get("rutas", [])
        if not isinstance(rutas, list) or any(not isinstance(p, str) for p in rutas):
            raise ErrorConvivencia("Rutas de ficha inválidas.", ruta)
        for destino in rutas:
            _patron(destino, "S", self.raices_solucion, ruta)
        return dict(datos, ruta=ruta, revision=revision, criterios=vigentes[revision],
                    referencia=f"{match[1]}@r{revision}")


def etiqueta(texto, campo_, valor):
    return re.search(rf"^\|\s*\*\*{re.escape(campo_)}\*\*\s*\|\s*{re.escape(valor)}\s*\|",
                     texto, re.MULTILINE) is not None


def _base_en(texto):
    for linea in texto.splitlines():
        if re.match(r"(?i)^\s*(?:[-*]\s+)?Base(?:\s+(?:local|observada|aprobada))?(?:\s|:)", linea):
            sha = re.search(rf"`({OID})`", linea)
            if sha:
                return sha[1]
        ampliacion = re.search(rf"(?i)\.\s+Base(?: local)?\s*:?[ \t]*`({OID})`", linea)
        if ampliacion:
            return ampliacion[1]
    return None


def _aprobaciones(cabecera, secciones, folio, version):
    ampliaciones = [(numero, titulo, contenido)
                    for numero, titulo, contenido in secciones if "ampliación" in titulo.lower()]
    base = next((sha for numero, _, contenido in secciones
                 if numero in (1, 2) and (sha := _base_en(contenido)) is not None), None)
    aprobaciones = {}
    linea = campo(cabecera, "Autorización") or ""
    citas = list(re.finditer(r"«([^»]+)»", linea))
    for indice, marca in enumerate(citas):
        cita = marca[1]
        numero = re.search(rf"{folio}\s+(v\d+(?:\.\d+)+)", cita, re.I)
        aplicable = numero[1] if numero else version
        cola = linea[marca.end():citas[indice + 1].start() if indice + 1 < len(citas) else len(linea)]
        huella = re.search(r"SHA-256\s+`([a-f0-9]{64})`", cola)
        if aplicable in aprobaciones:
            if aprobaciones[aplicable]["cita"] != cita:
                aprobaciones[aplicable]["ambigua"] = True
            continue
        aprobaciones[aplicable] = {
            "version": aplicable, "cita": cita, "base": base, "fuente": "cabecera",
            "procedencia": "cita_documentada",
        }
        if huella:
            aprobaciones[aplicable].update(sha256=huella[1], procedencia="presentado_pendiente")
    for numero, titulo, seccion in ampliaciones:
        referencia = re.search(r"(v\d+(?:\.\d+)+)", titulo)
        if not referencia:
            continue
        registro = aprobaciones.get(referencia[1])
        if registro is None:
            continue
        if f"«{registro['cita']}»" not in seccion:
            registro["ambigua"] = True
            continue
        base_ampliacion = _base_en(seccion)
        documento = re.search(r"\]\(([^)]+\.md)\)", seccion)
        huella = re.search(r"SHA-256\s+`([a-f0-9]{64})`", seccion)
        if base_ampliacion:
            registro["base"] = base_ampliacion
        registro["fuente"] = f"§{numero}"
        if documento and huella:
            registro.update(documento=documento[1], sha256=huella[1], procedencia="documento_citado")
    return aprobaciones
