"""Adaptador optativo de Codex para ediciones directas de ``solucion/``."""

from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import signal
import sys
from time import monotonic

from ..nucleo.acuerdos import _autoridad, preflight_nativo
from ..nucleo.arboles import ErrorArbol, LectorArbol, _git, _leer_trabajo, _raiz_repositorio, commit_lectura
from ..nucleo.convivencia import seleccionar_perfil
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import leer_inicio
from ..nucleo.modelo import coincide
from ..nucleo.modelo_sdd import leer
from ..nucleo.registro_sdd import _cotejar_legado, _deriva, _historial
from ..nucleo.verificacion import _raices_nativas, _reglas_nativas, evidencia_vigente


RUTA_HOOKS = ".codex/hooks.json"
MARCA = "Gobernanza local: edición directa de solución"
MATCHER = "^(apply_patch|Edit|Write|Bash)$"
PLAZO_VALIDACION = 135
TIMEOUT_CODEX = 180
_RAMAS = re.compile(r"refs/heads/codex/([SG][0-9]{2}-[0-9]{2})/([A-Za-z0-9][A-Za-z0-9_.-]*)")
_PARCHE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File:|Move to:) ([^\r\n]+)$", re.MULTILINE)
_LECTURAS = {"cat", "file", "head", "ls", "nl", "rg", "tail", "wc"}
_GIT_LECTURAS = {"branch", "diff", "log", "rev-parse", "show", "status"}
_OPCIONES_DIRECTAS = {
    "rm": ("fRiIrvd", {"force", "recursive", "interactive", "verbose", "dir"}),
    "mv": ("finv", {"force", "interactive", "no-clobber", "verbose"}),
    "touch": ("amch", {"no-create", "no-dereference"}),
    "cp": ("finpRPprvHLa", {"force", "interactive", "no-clobber", "recursive", "preserve", "verbose", "archive"}),
    "mkdir": ("pv", {"parents", "verbose"}),
}


def _objeto(datos):
    valor = json_estricto(datos.decode("utf-8"))
    if not isinstance(valor, dict):
        raise ValueError("Se requiere un objeto JSON.")
    return valor


def _configuracion(raiz):
    entrada = _leer_trabajo(raiz, RUTA_HOOKS)
    modo, anterior = entrada or ("100644", b'{"hooks":{}}')
    if modo not in {"100644", "100755"}:
        raise ValueError(f"{RUTA_HOOKS} debe ser un archivo regular.")
    config = _objeto(anterior)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{RUTA_HOOKS} requiere un objeto hooks.")
    grupos = hooks.setdefault("PreToolUse", [])
    if not isinstance(grupos, list):
        raise ValueError(f"{RUTA_HOOKS} requiere una lista PreToolUse.")
    gestionados = []
    for existente in grupos:
        if not isinstance(existente, dict) or not isinstance(existente.get("hooks"), list):
            raise ValueError(f"{RUTA_HOOKS} contiene un grupo PreToolUse inválido.")
        for handler in existente["hooks"]:
            if not isinstance(handler, dict):
                raise ValueError(f"{RUTA_HOOKS} contiene un handler PreToolUse inválido.")
            if handler.get("statusMessage") == MARCA or "hook-solucion ejecutar" in str(handler.get("command", "")):
                gestionados.append(existente)
    return modo, anterior, config, grupos, gestionados


def gestionado(raiz):
    """Detecta un hook dependiente del slot instalado, incluso si fue editado."""
    return bool(_configuracion(_raiz_repositorio(raiz))[-1])


def planificar(raiz, *, lanzador=".gobernanza-kit/gestionar.py"):
    """Calcula la única imagen gestionada, sin publicar ni activar nada."""
    raiz = _raiz_repositorio(raiz)
    relativo = PurePosixPath(lanzador)
    if (relativo.as_posix() != lanzador or len(relativo.parts) < 2 or relativo.name != "gestionar.py"
            or any(re.fullmatch(r"[A-Za-z0-9._-]+", p) is None or p in {".", ".."} for p in relativo.parts)):
        raise ValueError("La entrada del hook requiere el administrador relativo de la instalación.")
    modo, anterior, config, grupos, gestionados = _configuracion(raiz)
    comando = f'python3 "$(git rev-parse --show-toplevel)/{lanzador}" hook-solucion ejecutar'
    grupo = {"matcher": MATCHER, "hooks": [
        {"type": "command", "command": comando, "statusMessage": MARCA, "timeout": TIMEOUT_CODEX},
    ]}
    if gestionados:
        if gestionados != [grupo]:
            raise ValueError(f"La entrada gestionada de {RUTA_HOOKS} difiere; conserva y concilia su configuración.")
        return {RUTA_HOOKS: (modo, anterior)}
    grupos.append(grupo)
    return {RUTA_HOOKS: (modo, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))}


def _operandos_literales(nombre, argumentos):
    cortas, largas = _OPCIONES_DIRECTAS[nombre]
    operandos = []
    opciones = True
    for token in argumentos:
        if opciones and token == "--":
            opciones = False
        elif opciones and token.startswith("--"):
            if token[2:] not in largas:
                return []
        elif opciones and token.startswith("-"):
            if len(token) == 1 or not set(token[1:]) <= set(cortas):
                return []
        elif not token:
            return []
        else:
            operandos.append(token)
    return operandos


def _clasificar_shell(comando):
    if not isinstance(comando, str) or any(c in comando for c in ("\n", "\r", "`", "$", ";", "&", "|", "*", "?", "<")):
        return "indeterminada", []
    try:
        tokens = shlex.split(comando)
    except ValueError:
        return "indeterminada", []
    if not tokens:
        return "indeterminada", []
    nombre, *argumentos = tokens
    if ">" in comando:
        # Un único operador literal y final en comandos de salida conocidos.
        # Las redirecciones agrupadas, sustituciones y scripts siguen opacos.
        simple = re.fullmatch(r"(?:cat|echo|printf)[ \t]+[^<>]+[ \t]+>>?[ \t]+([^<>]+)", comando)
        if simple and len(tokens) >= 3 and tokens[-2] in {">", ">>"} and nombre in {"cat", "echo", "printf"}:
            return "escritura", [tokens[-1]]
        return "indeterminada", []
    if nombre in _LECTURAS or (nombre == "git" and argumentos and argumentos[0] in _GIT_LECTURAS):
        return "permitir", []
    if nombre in _OPCIONES_DIRECTAS:
        operandos = _operandos_literales(nombre, argumentos)
        if nombre in {"cp", "mv"}:
            if len(operandos) >= 2 and all(PurePosixPath(p).name not in {"", ".", ".."} for p in operandos[:-1]):
                return nombre, operandos
        elif operandos:
            return "escritura", operandos
    return "indeterminada", []


def _invocacion(herramienta, entrada):
    if herramienta == "apply_patch":
        texto = entrada.get("command", entrada.get("patch"))
        if isinstance(texto, str):
            rutas = _PARCHE.findall(texto)
            if rutas:
                return "escritura", rutas
    elif herramienta in {"Edit", "Write"}:
        ruta = entrada.get("file_path", entrada.get("path"))
        if isinstance(ruta, str) and ruta:
            return "escritura", [ruta]
    elif herramienta == "Bash":
        return _clasificar_shell(entrada.get("command", entrada.get("cmd")))
    return "indeterminada", []


def _decidir(decision, codigo, mensaje="", rutas=()):
    return dict(decision=decision, codigo=codigo, mensaje=mensaje, rutas=sorted(set(rutas)))


def _raiz_efectiva(cwd, entrada):
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("La llamada no identifica un cwd absoluto.")
    efectiva = entrada.get("workdir", entrada.get("cwd", cwd))
    if not isinstance(efectiva, str) or not efectiva:
        raise ValueError("El directorio efectivo de la herramienta no es válido.")
    carpeta = (Path(cwd) / efectiva).resolve(strict=True)
    try:
        raiz = _git(carpeta, "rev-parse", "--show-toplevel").decode().rstrip("\n")
    except ErrorArbol:
        return carpeta, None
    return carpeta, _raiz_repositorio(raiz)


def _ruta_solucion(raiz, destino):
    solucion = raiz / "solucion"
    if destino.is_relative_to(solucion):
        return destino.relative_to(raiz).as_posix()
    try:
        identidad = solucion.lstat()
    except OSError:
        return None
    for ancestro in (destino, *destino.parents):
        try:
            if os.path.samestat(identidad, ancestro.lstat()):
                return (PurePosixPath("solucion") / destino.relative_to(ancestro)).as_posix()
        except OSError:
            continue
    return None


def _destinos(raiz, carpeta, destinos):
    rutas, escapes = set(), set()
    for destino in destinos:
        literal = _ruta_solucion(raiz, Path(os.path.abspath(carpeta / destino)))
        try:
            efectiva = _ruta_solucion(raiz, (carpeta / destino).resolve())
        except (OSError, RuntimeError, ValueError):
            efectiva = None
        if efectiva is not None:
            rutas.add(efectiva)
        if literal is not None:
            (rutas if efectiva is not None else escapes).add(literal)
    return rutas, escapes


def _destinos_traslado(accion, carpeta, operandos):
    *origenes, destino = operandos
    if len(origenes) > 1 or destino.endswith("/") or (carpeta / destino).is_dir():
        escritos = [str(Path(destino) / PurePosixPath(ruta).name) for ruta in origenes]
    else:
        escritos = [destino]
    return [*origenes, *escritos] if accion == "mv" else escritos


def _esta_en(ruta, patrones):
    return any(coincide(ruta, patron) for patron in patrones)


def _informe(lector, ruta, folio):
    informe = _objeto(lector.leer(ruta))
    if (informe.get("sesion") == folio and informe.get("etapa") == "preparacion"
            and informe.get("preparacion_satisfecha") is True):
        return informe
    return None


def _estandar(raiz, cabeza, rama, folio, rutas):
    trabajo, indice = LectorArbol(raiz, "worktree"), LectorArbol(raiz, "staged")
    errores, operaciones = _historial(cabeza)
    for lector in (trabajo, indice):
        errores.extend(_deriva(cabeza, lector))
        if not errores:
            errores.extend(_cotejar_legado(lector, operaciones))
    if errores:
        raise ValueError(errores[0]["mensaje"])
    captura = leer_inicio(raiz, folio)
    ruta_sesion = captura["ruta_sesion"]
    ruta_config = "gobernanza/config.json"
    for ruta in (ruta_sesion, ruta_config):
        if cabeza.entrada(ruta) != trabajo.entrada(ruta) or cabeza.entrada(ruta) != indice.entrada(ruta):
            raise ValueError(f"La autoridad tiene cambios locales en {ruta}.")
    datos, prosa = leer(cabeza.leer(ruta_sesion).decode("utf-8"))
    autoridad = _autoridad(datos, "\n".join(prosa.splitlines()), folio)
    if autoridad != captura["datos"]:
        raise ValueError("La sesión actual difiere de su captura de inicio.")
    acuerdo = autoridad["acuerdo"]
    if acuerdo.get("rama") != rama:
        raise ValueError(f"El mandato aprobado de {folio} debe declarar la ref exacta {rama}.")
    estado = datos.get("estado")
    if estado not in {"preparacion", "ejecucion"}:
        raise ValueError(f"La sesión {folio} está en {estado!r}; esta fase no admite ediciones.")
    alcance = acuerdo["alcance"]
    config = _objeto(cabeza.leer(ruta_config))
    pruebas = config.get("raices", {}).get("pruebas", [])
    controles = config.get("raices", {}).get("controles", [])
    producto = []
    for ruta in sorted(rutas):
        if ruta in acuerdo["scaffold"]:
            continue
        if _esta_en(ruta, [*controles, *alcance["controles"]]):
            if folio.startswith("G") and _esta_en(ruta, alcance["controles"]):
                continue
        elif _esta_en(ruta, [*pruebas, *alcance["pruebas"]]):
            if _esta_en(ruta, alcance["pruebas"]):
                continue
        elif _esta_en(ruta, alcance["producto"]):
            producto.append(ruta)
            continue
        raise ValueError(f"La ruta {ruta} está fuera del alcance aprobado de {folio}.")
    if not producto:
        return
    if estado != "ejecucion":
        raise ValueError(f"{folio} requiere la fase ejecución antes de editar producto.")
    for ruta in datos.get("evidencias", []):
        if not ruta.endswith(".json") or cabeza.entrada(ruta) != trabajo.entrada(ruta) or cabeza.entrada(ruta) != indice.entrada(ruta):
            continue
        informe = _informe(cabeza, ruta, folio)
        if informe is not None and evidencia_vigente(raiz, informe, arbol="worktree")["vigente"]:
            return
    raise ValueError(f"Vincula la preparación real y vigente en evidencias de {folio}.")


def _nativo(repo, cabeza, folio, tx, actor, rutas):
    plan = repo.plan(folio)
    pruebas = _raices_nativas(repo.config)["pruebas"]
    producto = sorted(ruta for ruta in rutas if not _esta_en(ruta, pruebas))
    if not producto:
        ref = repo.git("log", "-1", "--format=%H", repo.head, "--", plan["ruta"]).decode().strip()
        entrada = dict(actor=actor, transaccion=tx, base=plan["base"], ref_acuerdo=ref,
                       version=plan["version"], cita=plan["cita"])
        preflight_nativo(repo, folio, entrada, rutas=rutas)
        return
    anexos = f"{plan['estado_modulo'].removesuffix('estado.md')}anexos/{folio}/"
    for ruta in cabeza.listar(anexos):
        if not ruta.endswith(".json") or not _esta_en(ruta, plan["alcance"]):
            continue
        if cabeza.entrada(ruta) != repo.lector.entrada(ruta):
            continue
        try:
            informe = _informe(cabeza, ruta, folio)
        except (TypeError, ValueError):
            continue
        if informe is None or informe.get("perfil_operacion") != repo.perfil:
            continue
        entrada = informe.get("entrada_nativa")
        if not isinstance(entrada, dict) or (entrada.get("actor"), entrada.get("transaccion")) != (actor, tx):
            continue
        preflight_nativo(repo, folio, entrada, rutas=rutas)
        if not evidencia_vigente(repo.raiz, informe, arbol="worktree")["vigente"]:
            continue
        if informe.get("pruebas_aprobadas") is True:
            conservacion = _reglas_nativas(repo, plan).get("conservacion")
            if not conservacion or any(not _esta_en(r, conservacion["rutas"]) for r in producto):
                continue
        elif not informe.get("esperados_rojos"):
            continue
        return
    raise ValueError(f"Falta preparación nativa vigente para {folio} y el actor del worktree.")


class _PlazoAgotado(BaseException):
    """Interrumpe incluso los validadores que convierten Exception en diagnóstico."""


def _interrumpir_validacion(*_):
    raise _PlazoAgotado()


@contextmanager
def _acotar_validacion(segundos):
    if segundos is None:
        yield
        return
    inicio = monotonic()
    previo, intervalo = signal.setitimer(signal.ITIMER_REAL, 0)
    manejador = signal.signal(signal.SIGALRM, _interrumpir_validacion)
    try:
        signal.setitimer(signal.ITIMER_REAL, segundos)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, manejador)
        if previo:
            restante = max(0.000001, previo - (monotonic() - inicio))
            signal.setitimer(signal.ITIMER_REAL, restante, intervalo)


def evaluar(datos, *, presupuesto=None):
    """Clasifica y coteja una invocación sin ejecutar herramientas ni escribir."""
    if not isinstance(datos, dict) or not isinstance(datos.get("tool_input"), dict):
        return _decidir("indeterminada", "HOOK_SOLUCION_ENTRADA")
    entrada = datos["tool_input"]
    decision, destinos = _invocacion(datos.get("tool_name"), entrada)
    if decision in {"permitir", "indeterminada"}:
        return _decidir(decision, "HOOK_SOLUCION_SIN_DESTINO")
    try:
        carpeta, raiz = _raiz_efectiva(datos.get("cwd"), entrada)
    except (ValueError, OSError, RuntimeError) as exc:
        return _decidir("indeterminada", "HOOK_SOLUCION_CWD", str(exc))
    if raiz is None:
        return _decidir("permitir", "HOOK_SOLUCION_FUERA_DE_REPOSITORIO")
    if decision in {"cp", "mv"}:
        destinos = _destinos_traslado(decision, carpeta, destinos)
    rutas, escapes = _destinos(raiz, carpeta, destinos)
    if escapes:
        return _decidir("denegar", "HOOK_SOLUCION_ENLACE", "Un destino de solución escapa de la raíz efectiva.", rutas | escapes)
    if not rutas:
        return _decidir("permitir", "HOOK_SOLUCION_FUERA_DE_SOLUCION")
    try:
        with _acotar_validacion(presupuesto):
            rama = _git(raiz, "symbolic-ref", "--quiet", "HEAD").decode().strip()
            vinculada = _RAMAS.fullmatch(rama)
            if not vinculada:
                raise ValueError("Abre la rama de ejecución exacta de una sesión G/S antes de editar solución.")
            folio, tx = vinculada.groups()
            cabeza = LectorArbol(raiz, "HEAD")
            repo = seleccionar_perfil(raiz, "worktree")
            if repo is None:
                _estandar(raiz, cabeza, rama, folio, rutas)
            else:
                _nativo(repo, cabeza, folio, tx, datos.get("session_id"), rutas)
            if (cabeza.commit != commit_lectura(raiz, "HEAD")
                    or rama != _git(raiz, "symbolic-ref", "--quiet", "HEAD").decode().strip()):
                raise ValueError("La rama o HEAD cambió durante el cotejo.")
    except _PlazoAgotado:
        return _decidir("denegar", "HOOK_SOLUCION_PLAZO",
                        "El cotejo de autoridad agotó su plazo. Reintenta la edición tras comprobar la sesión.", rutas)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return _decidir("denegar", "HOOK_SOLUCION_AUTORIDAD", str(exc), rutas)
    return _decidir("permitir", "HOOK_SOLUCION_AUTORIZADA", rutas=rutas)


def ejecutar():
    """Protocolo PreToolUse de Codex para el administrador instalado."""
    try:
        resultado = evaluar(json_estricto(sys.stdin.read()), presupuesto=PLAZO_VALIDACION)
    except (ValueError, OSError):
        return 0
    if resultado["decision"] == "denegar":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"[{resultado['codigo']}] {resultado['mensaje']}"
                                        f" Rutas: {', '.join(resultado['rutas'])}.",
        }}, ensure_ascii=False))
    return 0
