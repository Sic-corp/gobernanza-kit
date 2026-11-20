"""Verificación unittest real y evidencia ligada al contenido; F-0105@r1."""

import ast
from datetime import datetime
import fnmatch
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize

from .acuerdos import (_adicion_pura, capturar_acuerdo, huella_obligaciones_materializadas,
                       normalizar_autoridad, validar_cambios)
from .arboles import _leer_trabajo, _ruta, materializar
from .contexto import contexto
from .documentos import cargar, json_estricto
from .modelo import coincide, diagnostico, resultado


def _hash(datos):
    texto = json.dumps(datos, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _motor():
    return _hash({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(Path(__file__).parent.glob("*.py"))})


def _entradas(arbol, sesion, *, reanudacion=False):
    repo = cargar(arbol.raiz)
    if repo.errores:
        raise ValueError(json.dumps(repo.errores, ensure_ascii=False))
    config = repo.config
    raices = [p for grupo in config["raices"].values() for p in grupo]
    documentos = [*config["documentos"], "sdd/registro/*.md"]
    salidas = list(config.get("salidas", []))
    for verificador in config["verificadores"]:
        salidas.extend(verificador.get("salidas_permitidas", []))
    for salida in salidas:
        if repo.segura(salida) is None:
            raise ValueError("Salida fuera de la raíz declarada.")
    entradas = {}
    autoridad = normalizar_autoridad(arbol.raiz, sesion, reanudacion=reanudacion)
    for ruta, meta in arbol.archivos.items():
        necesaria = ruta in {"gobernanza/config.json", "sdd/proyecto.md"} or any(
            coincide(ruta, p) for p in raices + documentos)
        salida = any(coincide(ruta, p) for p in salidas)
        if necesaria and salida:
            raise ValueError(f"La salida declarada oculta una entrada: {ruta}")
        if necesaria:
            entradas[ruta] = dict(meta)
            if meta["modo"] == "120000":
                entradas[ruta]["destino_sha256"] = hashlib.sha256((arbol.raiz / ruta).read_bytes()).hexdigest()
            if ruta == autoridad["ruta_sesion"]:
                entradas[ruta]["sha256"] = _hash(autoridad["datos"])
                entradas[ruta]["normalizado"] = "autoridad"
    return repo, entradas, autoridad


def _parametros(raiz, verificador):
    raiz = raiz.resolve()
    args = verificador["args"]
    if verificador["runner"] != "unittest" or len(args) < 4 or args[1:4] != ["-m", "unittest", "discover"]:
        raise ValueError("Solo se soporta unittest discover con argumentos declarados.")
    ejecutable = shutil.which(args[0])
    if ejecutable is None or Path(ejecutable).resolve() != Path(sys.executable).resolve():
        raise ValueError("El intérprete declarado no coincide con el Python ejecutor del kit; no se sustituye silenciosamente.")
    opciones = {"inicio": ".", "patron": "test*.py", "top": None, "verbosity": 2, "buffer": False}
    claves = {"-s": "inicio", "--start-directory": "inicio", "-p": "patron", "--pattern": "patron",
              "-t": "top", "--top-level-directory": "top"}
    i = 4
    while i < len(args):
        argumento = args[i]
        if argumento in {"-v", "--verbose", "-q", "--quiet"}:
            opciones["verbosity"] = 0 if argumento in {"-q", "--quiet"} else 2
            i += 1
        elif argumento in {"-b", "--buffer"}:
            opciones["buffer"] = True
            i += 1
        elif argumento in claves and i + 1 < len(args):
            opciones[claves[argumento]] = args[i + 1]
            i += 2
        else:
            raise ValueError(f"Argumento unittest no soportado: {argumento}")
    cwd = (raiz / verificador.get("cwd", ".")).resolve()
    if not cwd.is_relative_to(raiz):
        raise ValueError("cwd sale del checkout materializado.")
    for clave in ("inicio", "top"):
        if opciones[clave] is not None:
            destino = (cwd / opciones[clave]).resolve()
            if not destino.is_relative_to(raiz):
                raise ValueError(f"{clave} sale del checkout materializado.")
            opciones[clave] = str(destino)
    return dict(opciones, cwd=str(cwd))


def _ejecutar(arbol, verificador, obligatorios, directorio, timeout):
    opciones = _parametros(arbol.raiz, verificador)
    salida = directorio / "resultado.json"
    job = dict(opciones, raiz=str(arbol.raiz), obligatorios=obligatorios, salida=str(salida))
    archivo_job = directorio / "trabajo.json"
    archivo_job.write_text(json.dumps(job), encoding="utf-8")
    comando = [sys.executable, "-I", str(Path(__file__).with_name("runner_unittest.py")), str(archivo_job)]
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    timeout_ocurrido = False
    try:
        proceso = subprocess.run(comando, cwd=opciones["cwd"], env=env, capture_output=True,
                                 text=True, timeout=timeout)
        codigo, stdout, stderr = proceso.returncode, proceso.stdout, proceso.stderr
    except subprocess.TimeoutExpired as exc:
        timeout_ocurrido = True
        codigo = None
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
    datos = {}
    if salida.exists():
        try:
            datos = json.loads(salida.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return dict(datos, id=verificador["id"], comando=comando, comando_configurado=verificador["args"],
                exit=codigo, stdout=stdout, stderr=stderr, timeout=timeout_ocurrido)


def _fallo(codigo, mensaje):
    return diagnostico(codigo, "verificacion", "Casos obligatorios realmente descubiertos y ejecutados",
                       mensaje, "Corrige la causa y vuelve a verificar el contenido pertinente.")


def _reglas_nativas(repo, plan):
    from .convivencia import campo

    texto = repo.leer(plan["ruta"]).decode("utf-8")
    inicio, fin = "<!-- gobernanza:verificacion -->", "<!-- /gobernanza:verificacion -->"
    if texto.count(inicio) != 1 or texto.count(fin) != 1 or texto.index(inicio) >= texto.index(fin):
        raise ValueError("El plan requiere una declaración de verificación nativa comprobable.")
    reglas = json_estricto(texto.split(inicio, 1)[1].split(fin, 1)[0])
    claves = {"unittest", "externos"}
    if not isinstance(reglas, dict) or not claves <= set(reglas) or set(reglas) - claves - {"criterios", "conservacion"}:
        raise ValueError("Declare los verificadores unittest y los requisitos externos del plan.")
    ids, externos = reglas["unittest"], reglas["externos"]
    if (not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids)
            or len(ids) != len(set(ids)) or not isinstance(externos, list)):
        raise ValueError("La selección de verificadores nativos es inválida o ambigua.")
    vistos = set()
    for requisito in externos:
        if not isinstance(requisito, dict):
            raise ValueError("Requisito externo inválido.")
        nombre, tipo = requisito.get("id"), requisito.get("tipo")
        if (not isinstance(nombre, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", nombre)
                or nombre in vistos or tipo not in {"suite", "build", "operacion", "humano"}):
            raise ValueError("Identidad o tipo de requisito externo inválido.")
        vistos.add(nombre)
        exigido = requisito.get("criterio") if tipo == "humano" else requisito.get("comando")
        if (tipo == "humano" and not isinstance(exigido, str)) or (
            tipo != "humano" and (not isinstance(exigido, list) or not exigido
                                   or any(not isinstance(a, str) or not a for a in exigido))
        ):
            raise ValueError(f"Falta criterio o comando explícito para {nombre}.")
        for clave in ("criterios", "regresiones"):
            referencias = requisito.get(clave, [])
            if not isinstance(referencias, list) or any(not isinstance(r, str) for r in referencias):
                raise ValueError(f"Obligaciones externas inválidas para {nombre}.")
        if requisito.get("regresiones") and tipo != "suite":
            raise ValueError("Las regresiones externas requieren inventario de suite.")
    declarados = reglas.get("criterios", [])
    if not isinstance(declarados, list) or any(not isinstance(c, str) for c in declarados):
        raise ValueError("Declare criterios nativos por revisión, criterio y selección.")
    conservacion = reglas.get("conservacion")
    if conservacion is not None:
        if (not isinstance(conservacion, dict) or not isinstance(conservacion.get("motivo"), str)
                or not conservacion["motivo"].strip() or not isinstance(conservacion.get("rutas"), list)
                or not conservacion["rutas"] or any(not isinstance(r, str) or not r for r in conservacion["rutas"])):
            raise ValueError("La conservación requiere motivo y rutas explícitas en el acuerdo.")
    cabecera = texto.split("\n##", 1)[0]
    regresion = campo(cabecera, "Regresión") or ""
    reglas["regresion"] = [r.strip().strip("`") for r in regresion.split(",") if r.strip()]
    return reglas


def _leer_criterios_nativos(repo, plan, regresion):
    criterios = {}
    for ref in dict.fromkeys([*plan["funcionalidades"], *regresion]):
        ficha = repo.ficha(ref)
        if ficha["id"] in criterios or ficha.get("estado") != "Validado" or ficha["referencia"] != ref:
            raise ValueError(f"Ficha o revisión no validada o ambigua al vincular {ref}.")
        criterios[ficha["id"]] = (ficha["referencia"], frozenset(ficha["criterios"]))
    return criterios

def _marcas_nativas(texto):
    comentarios = {t.start: t.string for t in tokenize.generate_tokens(io.StringIO(texto).readline)
                   if t.type == tokenize.COMMENT and t.string.startswith("# criterio:")}
    marcas = {}
    for clase in ast.parse(texto).body:
        if not isinstance(clase, ast.ClassDef):
            continue
        for metodo in clase.body:
            if not isinstance(metodo, ast.FunctionDef) or not metodo.name.startswith("test_"):
                continue
            linea = min([metodo.lineno] + [d.lineno for d in metodo.decorator_list]) - 1
            metadatos = []
            while (linea, metodo.col_offset) in comentarios:
                vinculo = comentarios[(linea, metodo.col_offset)].removeprefix("# criterio:").strip()
                metadatos.append((linea, vinculo))
                linea -= 1
            if metadatos:
                caso = f"{clase.name}.{metodo.name}"
                if caso in marcas:
                    raise ValueError(f"Método de prueba con identidad ambigua: {caso}.")
                marcas[caso] = list(reversed(metadatos))
    return marcas


def _resolver_criterio(marca, fichas):
    m = re.fullmatch(r"(F-\d{4})(?:@r([1-9]\d*))?/(C\d{2})", marca)
    if not m:
        raise ValueError(f"Marca de criterio nativo inválida: {marca}.")
    identidad, revision, criterio = m.groups()
    if identidad not in fichas:
        return None
    ref, admitidos = fichas[identidad]
    if (revision is not None and ref != f"{identidad}@r{revision}") or criterio not in admitidos:
        raise ValueError(f"Marca sin revisión o criterio válido para el acuerdo: {marca}.")
    return f"{ref}/{criterio}"


def _vinculos_nativos(copia, fichas, verificadores):
    salida = []
    raiz = copia.raiz.resolve()
    for verificador in verificadores:
        opciones = _parametros(raiz, verificador)
        inicio = Path(opciones["inicio"]).relative_to(raiz)
        top = Path(opciones["top"]).relative_to(raiz) if opciones["top"] else inicio
        por_selector = {}
        for ruta, meta in copia.archivos.items():
            archivo = Path(ruta)
            if not (archivo.is_relative_to(inicio) and archivo.is_relative_to(top)
                    and archivo.suffix == ".py" and fnmatch.fnmatchcase(archivo.name, opciones["patron"])):
                continue
            modulo = ".".join(archivo.relative_to(top).with_suffix("").parts)
            texto = (copia.raiz / ruta).read_text(encoding="utf-8")
            for metodo, marcas in _marcas_nativas(texto).items():
                selector = f"{modulo}.{metodo}"
                for linea, marca in marcas:
                    criterio = _resolver_criterio(marca, fichas)
                    if criterio is None:
                        continue
                    if por_selector.setdefault(selector, ruta) != ruta:
                        raise ValueError(f"Selector nativo ambiguo en {verificador['id']}: {selector}.")
                    salida.append(dict(criterio=criterio, verificador=verificador["id"],
                                       selector=selector, ruta=ruta, linea=linea, sha256=meta["sha256"]))
    return salida


def _raices_nativas(config):
    raices = config.get("raices", {})
    if (not isinstance(raices, dict) or set(raices) != {"pruebas", "controles", "solucion"}
            or any(not isinstance(grupo, list) or any(not isinstance(r, str) or not r for r in grupo)
                   for grupo in raices.values())):
        raise ValueError("Las raíces de pruebas, solución y controles deben estar declaradas.")
    return raices


def _cobertura_nativa(fichas, plan, reglas, vinculos):
    requeridos = reglas.get("criterios")
    if requeridos is None:
        requeridos = [f"{ref}/{c}" for ref, criterios in fichas.values()
                      if ref in plan["funcionalidades"] for c in criterios]
    externos = []
    regresion_externa = set()
    for requisito in reglas["externos"]:
        externos.extend(requisito.get("criterios", ()))
        if requisito["tipo"] == "humano":
            externos.append(requisito["criterio"])
        regresion_externa.update(requisito.get("regresiones", ()))
    for criterio in [*requeridos, *externos]:
        if _resolver_criterio(criterio, fichas) != criterio:
            raise ValueError(f"Se requiere revisión y criterio explícitos del acuerdo: {criterio}.")
    if regresion_externa - set(reglas["regresion"]):
        raise ValueError("Suite de regresión ajena a los contratos declarados.")
    comprobables = {v["criterio"] for v in vinculos} | set(externos)
    faltan = set(requeridos) - comprobables
    for ref in reglas["regresion"]:
        criterios = fichas[ref.split("@r")[0]][1]
        if ref not in regresion_externa:
            faltan.update({f"{ref}/{c}" for c in criterios} - comprobables)
    if faltan:
        raise ValueError("Cobertura nativa sin vínculo comprobable: " + ", ".join(sorted(faltan)))


def _anexos_nativos(plan):
    sesiones = plan["continuidad"].rsplit("/", 1)[0]
    return f"{sesiones}/modulos/{plan['modulo']}/anexos/"


def _entradas_nativas(copia, repo, plan):
    raices = _raices_nativas(repo.config)
    protegidas = raices["pruebas"] + raices["solucion"] + raices["controles"]
    anexos = _anexos_nativos(plan)
    salidas = set()
    raiz = copia.raiz.resolve()
    for grupo in [repo.config, *repo.config.get("verificadores", ())]:
        destinos = grupo.get("salidas", grupo.get("salidas_permitidas", ()))
        if (not isinstance(destinos, (list, tuple)) or any(not isinstance(r, str) for r in destinos)):
            raise ValueError("La declaración de salidas nativas es inválida.")
        for destino in destinos:
            if destino.startswith(anexos):
                if (Path(destino).as_posix() != destino.rstrip("/") or ".." in Path(destino).parts
                        or raiz / destino != (raiz / destino).resolve()):
                    raise ValueError(f"Salida nativa insegura: {destino}.")
                salidas.add(destino)
    incluidos = {}
    for ruta, meta in copia.archivos.items():
        if any(coincide(ruta, p) for p in salidas) or ruta.startswith(".heimdall/runtime/"):
            if any(coincide(ruta, p) for p in protegidas):
                raise ValueError(f"Una ruta de evidencia solapa entradas protegidas: {ruta}.")
            continue
        incluidos[ruta] = dict(meta)
        if meta["modo"] == "120000":
            destino = copia.raiz / ruta
            incluidos[ruta]["destino_sha256"] = (hashlib.sha256(destino.read_bytes()).hexdigest()
                                                 if destino.is_file() else None)
    return incluidos

def _obligaciones_nativas(entradas, config):
    raices = _raices_nativas(config)
    return _hash({ruta: meta for ruta, meta in entradas.items()
                  if not any(coincide(ruta, patron) for patron in raices["solucion"])
                  or any(coincide(ruta, patron) for patron in raices["pruebas"] + raices["controles"])})


def _leer_registro_externo(repo, nombre):
    if not isinstance(nombre, str):
        raise ValueError("Declara el archivo externo con su ruta absoluta.")
    archivo = Path(nombre)
    if not archivo.is_absolute() or archivo.suffix != ".json" or archivo != archivo.resolve(strict=True):
        raise ValueError("El archivo externo requiere una ruta absoluta efectiva a JSON regular.")
    dato = repo.git("worktree", "list", "--porcelain", "-z")
    worktrees = [Path(os.fsdecode(campo.removeprefix(b"worktree "))).resolve()
                 for campo in dato.split(b"\0") if campo.startswith(b"worktree ")]
    if any(archivo.is_relative_to(r) for r in [repo.raiz, repo.comun, *worktrees]):
        raise ValueError("El archivo de evidencia debe estar fuera de los worktrees y metadatos Git.")
    raiz = Path(archivo.anchor)
    imagen = _leer_trabajo(raiz, archivo.relative_to(raiz).as_posix())
    if not imagen or imagen[0] not in {"100644", "100755"}:
        raise ValueError("El archivo de evidencia debe ser regular.")
    return imagen[1]


def cotejar_registro_nativo(repo, plan, referencia):
    """Lee un registro cooperativo vinculado a un anexo canónico y a sus bytes."""
    if (not isinstance(referencia, dict) or set(referencia) - {"ruta", "ref", "archivo", "sha256"}
            or "ref" in referencia and "archivo" in referencia):
        raise ValueError("Referencia de evidencia nativa inválida.")
    ruta = _ruta(referencia.get("ruta"))
    anexos = _anexos_nativos(plan)
    if not ruta.startswith(anexos) or not ruta.endswith(".json"):
        raise ValueError("La evidencia debe pertenecer a los anexos del módulo primario.")
    vista = repo
    if "ref" in referencia:
        if not isinstance(referencia["ref"], str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", referencia["ref"]):
            raise ValueError("Use el commit exacto de la evidencia externa.")
        vista = repo.en_arbol(referencia["ref"], historico=True)
    cuerpo = (_leer_registro_externo(repo, referencia["archivo"])
              if "archivo" in referencia else vista.leer(ruta))
    if hashlib.sha256(cuerpo).hexdigest() != referencia.get("sha256"):
        raise ValueError(f"Cambió la huella del registro {ruta}.")
    datos = json_estricto(cuerpo.decode("utf-8"))
    if (not isinstance(datos, dict) or datos.get("proyecto") != plan["proyecto"]
            or datos.get("folio") != plan["folio"]):
        raise ValueError(f"Evidencia ajena al folio o proyecto en {ruta}.")
    return datos


def _evidencia_nativa(repo, plan, requisitos, referencias, versiones):
    if not isinstance(referencias, list):
        raise ValueError("Las evidencias nativas se declaran mediante referencias exactas.")
    esperados = {r["id"]: r for r in requisitos}
    encontrados = {}
    for fuente in referencias:
        datos = cotejar_registro_nativo(repo, plan, fuente)
        identidad = datos.get("id")
        if not isinstance(identidad, str) or identidad in encontrados or identidad not in esperados:
            raise ValueError("Registro nativo repetido o ajeno al plan.")
        req = esperados[identidad]
        if datos.get("estado") != "pasa" or datos.get("version") not in versiones or datos.get("tipo") != req["tipo"]:
            raise ValueError(f"Estado, tipo o versión inadecuados en {identidad}.")
        if any(not isinstance(datos.get(k), str) or not datos[k].strip()
               for k in ("fecha", "actor", "referencia")):
            raise ValueError(f"Falta procedencia para {identidad}.")
        if datetime.fromisoformat(datos["fecha"]).tzinfo is None:
            raise ValueError("El registro de evidencia requiere fecha con zona.")
        if req["tipo"] == "humano":
            if datos.get("criterio") != req["criterio"]:
                raise ValueError(f"Criterio humano ajeno al acuerdo en {identidad}.")
        elif (type(datos.get("exit")) is not int or datos["exit"] != 0
              or datos.get("comando") != req["comando"]
              or not isinstance(datos.get("entorno"), dict) or not datos["entorno"]
              or not isinstance(datos.get("salida"), str) or not datos["salida"].strip()):
            raise ValueError(f"Resultado reproducible incompleto en {identidad}.")
        if (datos.get("criterios", []) != req.get("criterios", [])
                or datos.get("regresiones", []) != req.get("regresiones", [])):
            raise ValueError(f"Cobertura externa ajena a la declaración {identidad}.")
        encontrados[identidad] = dict(datos, fuente=fuente)
    faltantes = sorted(set(esperados) - set(encontrados))
    for identidad, datos in encontrados.items():
        req = esperados[identidad]
        if req["tipo"] == "suite":
            casos = datos.get("casos")
            obligatorios = req.get("obligatorios", [])
            alternativas = req.get("omisiones", {})
            if (not isinstance(casos, dict) or not casos or not isinstance(obligatorios, list)
                    or any(not isinstance(c, str) for c in obligatorios)
                    or not isinstance(alternativas, dict) or any(
                        e not in ("aprobado", "omitido") for e in casos.values()
                    ) or not set(obligatorios) <= set(casos)):
                raise ValueError(f"Inventario de suite incompleto en {identidad}.")
            for caso, estado in casos.items():
                if estado == "omitido":
                    regla = alternativas.get(caso, {})
                    alterna = encontrados.get(regla.get("id"), {})
                    if (alterna.get("casos", {}).get(caso) != "aprobado"
                            or not regla.get("plataforma")
                            or alterna.get("entorno", {}).get("plataforma") != regla["plataforma"]):
                        raise ValueError(f"Omisión sin ejecución de plataforma acreditada: {caso}.")
    return list(encontrados.values()), faltantes


def _pruebas_sensibles_nativas(base, copia, entradas_base, entradas, control, raices):
    for ruta, meta in entradas_base.items():
        actual = entradas.get(ruta)
        if meta == actual or not any(coincide(ruta, p) for p in raices):
            continue
        if actual and ruta.endswith(".py") and meta["modo"] == actual["modo"] == "100644":
            viejo = (base.raiz / ruta).read_text(encoding="utf-8")
            nuevo = (copia.raiz / ruta).read_text(encoding="utf-8")
            marcas_antes = _marcas_nativas(viejo)
            marcas_despues = _marcas_nativas(nuevo)
            marcas_iguales = all([m for _, m in marcas] == [m for _, m in marcas_despues.get(caso, ())]
                                 for caso, marcas in marcas_antes.items())
            if marcas_iguales and _adicion_pura(viejo, nuevo):
                continue
        if not any(d["ruta"] == ruta and d.get("sha256") for d in control.get("excepciones", ())):
            return ruta
    return None


class _DictamenNativoRequerido(ValueError):
    """Una obligación aceptada cambió sin dictamen independiente aplicable."""


def _preparacion_nativa(repo, control, copia, base, preparacion, *, etapa, entrada=None):
    from .acuerdos import preflight_nativo

    plan = control["plan"]
    entradas = _entradas_nativas(copia, repo, plan)
    anteriores = _entradas_nativas(base, repo, plan)
    cambios = [ruta for ruta in sorted(entradas.keys() | anteriores.keys())
               if entradas.get(ruta) != anteriores.get(ruta)]
    if entrada is not None:
        control = preflight_nativo(repo, plan["folio"], entrada, rutas=cambios, fase=etapa)
    raices = _raices_nativas(repo.config)
    ruta = _pruebas_sensibles_nativas(base, copia, anteriores, entradas, control, raices["pruebas"])
    if ruta:
        raise _DictamenNativoRequerido(f"Cambio sensible en {ruta}.")
    producto = [ruta for ruta in cambios if any(coincide(ruta, p) for p in raices["solucion"])
                and not any(coincide(ruta, p) for p in raices["pruebas"])]
    if producto:
        if (etapa == "preparacion" or not isinstance(preparacion, dict)
                or preparacion.get("etapa") != "preparacion"
                or preparacion.get("preparacion_satisfecha") is not True
                or preparacion.get("huella_acuerdo") != control["huella_acuerdo"]
                or not evidencia_vigente(repo.raiz, preparacion, arbol=repo.arbol)["vigente"]):
            raise ValueError("La conducta requiere preparación nativa previa y vigente.")
        if preparacion.get("pruebas_aprobadas") is True:
            conservacion = _reglas_nativas(repo, plan).get("conservacion")
            if not conservacion or any(not any(coincide(ruta, p) for p in conservacion["rutas"]) for ruta in producto):
                raise ValueError("Un verde previo requiere conservación motivada para esas rutas.")
        elif not preparacion.get("esperados_rojos"):
            raise ValueError("Falta un fallo de aserción previo atribuible al cambio.")
    return dict(entradas=entradas, huella_entradas=_hash(entradas),
                huella_obligaciones=_obligaciones_nativas(entradas, repo.config))


def validar_preparacion_nativa(repo, control, *, preparacion=None, dictamenes=()):
    """Comprueba obligaciones del candidato. Las excepciones provienen del preflight."""
    if dictamenes:
        raise ValueError("Las excepciones nativas requieren registros anclados en entrada_nativa.excepciones.")
    with materializar(repo.raiz, repo.arbol) as copia, materializar(repo.raiz, control["base"]) as base:
        return _preparacion_nativa(repo, control, copia, base, preparacion, etapa="trabajo")


def _ejecutar_seleccion_nativa(salida, copia, vinculos, verificadores, temporal, timeout):
    requeridos = {}
    for indice, verificador in enumerate(verificadores):
        identidad = verificador["id"]
        seleccion = {}
        for vinculo in vinculos:
            if vinculo["verificador"] == identidad:
                seleccion.setdefault(vinculo["selector"], set()).add(vinculo["criterio"])
        if not seleccion:
            salida["errores"].append(_fallo("CASOS_NATIVOS_AUSENTES", f"Cero casos declarados para {identidad}."))
            continue
        requeridos.update({f"{identidad}::{selector}": criterios for selector, criterios in seleccion.items()})
        carpeta = Path(temporal) / str(indice)
        carpeta.mkdir()
        datos = _ejecutar(copia, verificador, sorted(seleccion), carpeta, timeout)
        salida["verificadores"].append(datos)
        for clave in ("casos_descubiertos", "casos_ejecutados"):
            salida[clave].extend(f"{identidad}::{s}" for s in datos.get(clave, ()))
        for caso in datos.get("resultados", ()):
            selector = caso["selector"]
            salida["resultados"].append(dict(caso, verificador=identidad,
                                               caso=f"{identidad}::{selector}",
                                               criterios=sorted(seleccion.get(selector, ()))))
        if datos["timeout"]:
            salida["errores"].append(_fallo("TIMEOUT", f"{identidad} excedió su tiempo."))
        elif (not datos.get("completa") or datos.get("errores_descubrimiento")
              or datos.get("ausentes") or datos["exit"] not in {0, 1}):
            salida["errores"].append(_fallo("RUNNER_INCOMPLETO", f"Ejecución incompleta en {identidad}."))
    return requeridos


def _verificar_nativo(repo, salida, entrada, esperados, preparacion, dictamenes, timeout):
    from .acuerdos import comprobar_autoridad_nativa

    sesion, etapa = salida["sesion"], salida["etapa"]
    control = comprobar_autoridad_nativa(repo, sesion, entrada)
    plan = control["plan"]
    reglas = _reglas_nativas(repo, plan)
    ancla = repo.en_arbol(entrada["ref_acuerdo"], historico=True)
    if (_reglas_nativas(ancla, ancla.plan(sesion)) != reglas
            or any(repo.config.get(c) != ancla.config.get(c) for c in ("verificadores", "raices"))):
        raise ValueError("Cambiaron la selección o las obligaciones aprobadas.")
    config = repo.config.get("verificadores")
    if not isinstance(config, list) or any(not isinstance(v, dict) or not isinstance(v.get("id"), str) for v in config):
        raise ValueError("La configuración de verificadores nativos es inválida.")
    por_id = {v["id"]: v for v in config}
    if len(por_id) != len(config) or not set(reglas["unittest"]) <= set(por_id):
        raise ValueError("Verificador nativo ausente o ambiguo.")
    verificadores = [por_id[i] for i in reglas["unittest"]]
    with (materializar(repo.raiz, repo.arbol) as copia,
          materializar(repo.raiz, control["base"]) as base,
          tempfile.TemporaryDirectory(prefix="gobernanza-informe-nativo-") as temporal):
        try:
            condicion = _preparacion_nativa(repo, control, copia, base, preparacion, etapa=etapa, entrada=entrada)
            if dictamenes:
                raise _DictamenNativoRequerido("Coteja las referencias en entrada_nativa.excepciones.")
        except _DictamenNativoRequerido as exc:
            salida["errores"].append(_fallo("DICTAMEN_NATIVO_REQUERIDO", str(exc)))
            return
        huella_entradas = condicion["huella_entradas"]
        salida.update(perfil_operacion="heimdall-v2", proyecto=repo.proyecto,
                      arbol=dict(selector=repo.arbol, commit=copia.commit, huella=copia.huella),
                      huella_acuerdo=control["huella_acuerdo"], entrada_nativa=entrada,
                      version_motor=_motor(), python=sys.version.split()[0], esperados_rojos=esperados,
                      **condicion)
        fichas = _leer_criterios_nativos(repo, plan, reglas["regresion"])
        vinculos = _vinculos_nativos(copia, fichas, verificadores)
        if vinculos or not verificadores:
            _cobertura_nativa(fichas, plan, reglas, vinculos)
        salida["vinculos_nativos"] = vinculos
        requeridos = _ejecutar_seleccion_nativa(salida, copia, vinculos, verificadores, temporal, timeout)
        estados = {r["caso"]: r["estado"] for r in salida["resultados"]}
        ejecutados = salida["casos_ejecutados"]
        salida["limites"]["pruebas_ejecutadas"] = bool(ejecutados)
        salida["limites"]["descubrimiento_runner"] = bool(salida["verificadores"])
        if set(ejecutados) != set(requeridos) or len(ejecutados) != len(requeridos):
            salida["errores"].append(_fallo("CASOS_AUSENTES", "Los casos ejecutados difieren de la selección."))
        verde = set(estados) == set(requeridos) and all(e == "aprobado" for e in estados.values())
        rojo = (bool(esperados) and set(esperados) <= set(requeridos) and set(estados) == set(requeridos)
                and all(e == ("fallo" if s in esperados else "aprobado") for s, e in estados.items()))
        if not (verde and not esperados) and not (etapa == "preparacion" and rojo):
            salida["errores"].append(_fallo("PRUEBAS_NO_APROBADAS", "La selección contiene resultados no admitidos."))
        if etapa == "entrega":
            versiones = {v for v in (copia.commit, huella_entradas) if v is not None}
            registros, faltan = _evidencia_nativa(repo, plan, reglas["externos"], entrada.get("evidencias", []), versiones)
            salida["evidencia_nativa"] = registros
            if faltan:
                salida["errores"].append(_fallo("EVIDENCIA_NATIVA_PENDIENTE", ", ".join(faltan)))
        else:
            registros = []
        if not requeridos and not any(registro["tipo"] == "suite" for registro in registros):
            salida["errores"].append(_fallo("CASOS_NATIVOS_AUSENTES", "Falta una suite comprobable para el folio."))
        salida["pruebas_aprobadas"] = verde and not salida["errores"]
        salida["preparacion_satisfecha"] = etapa == "preparacion" and not salida["errores"]


def _evidencia_vigente_nativa(raiz, informe, arbol):
    from .acuerdos import comprobar_autoridad_nativa, procedencia_acuerdo_nativo
    from .convivencia import seleccionar_perfil

    repo = seleccionar_perfil(raiz, arbol, requiere_nativo=True)
    entrada = informe["entrada_nativa"]
    plan = repo.plan(informe["sesion"])
    if repo.commit is None:
        origen = comprobar_autoridad_nativa(repo, informe["sesion"], entrada)
    else:
        rama = f"refs/heads/codex/{informe['sesion']}/{entrada['transaccion']}"
        repo.git("merge-base", "--is-ancestor", repo.commit, repo.commit_ref(rama))
        origen = procedencia_acuerdo_nativo(
            repo, informe["sesion"], ref_acuerdo=entrada["ref_acuerdo"],
            base=entrada["base"], transaccion=entrada["transaccion"],
        )
    actual = origen["huella_acuerdo"]
    if actual != informe["huella_acuerdo"]:
        raise ValueError("El acuerdo anclado difiere del que originó la verificación.")
    with materializar(raiz, repo.arbol) as copia:
        entradas = _entradas_nativas(copia, repo, plan)
        if informe["etapa"] == "preparacion":
            if _obligaciones_nativas(entradas, repo.config) != informe["huella_obligaciones"]:
                raise ValueError("Cambiaron las obligaciones nativas comprobadas.")
            return
        if informe["etapa"] != "entrega" or _hash(entradas) != informe["huella_entradas"]:
            raise ValueError("Cambió la identidad de las entradas nativas.")
        reglas = _reglas_nativas(repo, plan)
        versiones = {v for v in (copia.commit, informe["huella_entradas"]) if v is not None}
        actuales, faltan = _evidencia_nativa(repo, plan, reglas["externos"], entrada.get("evidencias", []), versiones)
        if faltan or actuales != informe.get("evidencia_nativa"):
            raise ValueError("Cambió una evidencia externa requerida.")


def verificar(raiz, sesion, *, arbol="staged", etapa="preparacion", acuerdo=None,
              esperados_rojos=None, preparacion=None, dictamenes=(), destino=None, timeout=30, entrada_nativa=None):
    salida = resultado("verificar")
    salida.update(schema=1, etapa=etapa, sesion=sesion, preparacion_satisfecha=False, pruebas_aprobadas=False,
                  casos_descubiertos=[], casos_ejecutados=[], resultados=[], verificadores=[],
                  resumen="Verificación real de unittest; no acepta entrega humana ni integración.")
    esperados = {} if esperados_rojos is None else esperados_rojos
    destino_permitido = False
    try:
        if (etapa not in {"preparacion", "entrega"} or type(timeout) not in {int, float}
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Etapa o timeout inválidos.")
        if not isinstance(esperados, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                                                 for k, v in esperados.items()):
            raise ValueError("Cada rojo esperado necesita selector y motivo no vacíos.")
        if etapa == "entrega" and esperados:
            raise ValueError("Entrega no admite rojos esperados.")
        raiz = Path(raiz).resolve()
        from .convivencia import seleccionar_perfil

        nativo = seleccionar_perfil(raiz, arbol, requiere_nativo=entrada_nativa is not None)
        if nativo is not None:
            if destino is not None:
                raise ValueError("El perfil nativo devuelve el informe para que el escritor lo conserve.")
            if acuerdo is not None and entrada_nativa is not None:
                raise ValueError("Proporcione una sola entrada de autoridad nativa.")
            entrada = entrada_nativa if entrada_nativa is not None else acuerdo
            if not isinstance(entrada, dict):
                raise ValueError("La verificación nativa requiere actor, acuerdo y referencias aprobadas.")
            _verificar_nativo(nativo, salida, entrada, esperados, preparacion, dictamenes, timeout)
        else:
            if destino is not None and Path(destino).resolve().is_relative_to(raiz):
                raise ValueError("El destino del informe debe quedar fuera del origen.")
            destino_permitido = destino is not None
            acuerdo = capturar_acuerdo(raiz, sesion) if acuerdo is None else acuerdo
            control = validar_cambios(raiz, sesion, acuerdo, arbol=arbol,
                                     fase="preparacion" if etapa == "preparacion" else "entrega",
                                     preparacion=preparacion, dictamenes=dictamenes)
            salida["validacion_cambios"] = control
            if control["codigo"]:
                salida["errores"].extend(control["errores"])
                raise ValueError("El candidato no satisface acuerdo, alcance o preparación.")
            with materializar(raiz, arbol) as copia, tempfile.TemporaryDirectory(prefix="gobernanza-informe-") as temporal:
                if destino is not None and Path(destino).resolve().is_relative_to(copia.raiz.resolve()):
                    destino_permitido = False
                    raise ValueError("El informe no se escribe en el checkout probado.")
                repo, entradas, autoridad = _entradas(copia, sesion)
                if autoridad["huella_acuerdo"] != acuerdo["huella_acuerdo"]:
                    raise ValueError("El contenido candidato cambia el acuerdo capturado.")
                contexto_sesion = contexto(copia.raiz, sesion=sesion)
                if contexto_sesion["codigo"]:
                    salida["errores"].extend(contexto_sesion["errores"])
                    raise ValueError("El contexto obligatorio no es resoluble.")
                pruebas = contexto_sesion["pruebas_declaradas"]
                obligatorios = {p["selector"] for p in pruebas}
                if not obligatorios:
                    raise ValueError("Cero casos obligatorios no constituye aceptación.")
                if set(esperados) - obligatorios:
                    raise ValueError("Un rojo esperado no corresponde a un caso obligatorio declarado.")
                salida.update(arbol={"selector": arbol, "huella": copia.huella, "commit": copia.commit},
                              huella_acuerdo=acuerdo["huella_acuerdo"], acuerdo=acuerdo,
                              huella_obligaciones=huella_obligaciones_materializadas(copia.raiz),
                              huella_entradas=_hash(entradas), entradas=entradas,
                              version_motor=_motor(), esperados_rojos=esperados,
                              proyecto=repo.config["proyecto"], python=sys.version.split()[0])
                for numero, verificador in enumerate(repo.config["verificadores"]):
                    seleccion = sorted(p["selector"] for p in pruebas if p["verificador"] == verificador["id"])
                    if not seleccion:
                        continue
                    carpeta = Path(temporal) / str(numero)
                    carpeta.mkdir()
                    datos = _ejecutar(copia, verificador, seleccion, carpeta, timeout)
                    salida["verificadores"].append(datos)
                    salida["casos_descubiertos"].extend(datos.get("casos_descubiertos", []))
                    salida["casos_ejecutados"].extend(datos.get("casos_ejecutados", []))
                    salida["resultados"].extend(datos.get("resultados", []))
                    if datos["timeout"]:
                        salida["errores"].append(_fallo("TIMEOUT", f"El verificador {verificador['id']} excedió su tiempo."))
                    elif (not datos.get("completa") or datos.get("errores_descubrimiento")
                          or datos.get("ausentes") or datos["exit"] not in {0, 1}):
                        salida["errores"].append(_fallo("RUNNER_INCOMPLETO", f"Inventario o ejecución incompletos en {verificador['id']}."))
                ejecutados = salida["casos_ejecutados"]
                if set(ejecutados) != obligatorios or len(ejecutados) != len(obligatorios):
                    salida["errores"].append(_fallo("CASOS_AUSENTES", "No se ejecutaron exactamente todos los casos obligatorios."))
                estados = {r["selector"]: r["estado"] for r in salida["resultados"]}
                verdes = len(estados) == len(obligatorios) and all(e == "aprobado" for e in estados.values())
                rojo_valido = (bool(esperados) and set(estados) == obligatorios
                               and all(e == ("fallo" if s in esperados else "aprobado") for s, e in estados.items()))
                if not verdes and not (etapa == "preparacion" and rojo_valido):
                    salida["errores"].append(_fallo("PRUEBAS_NO_APROBADAS", "Hay fallos, errores, omisiones o resultados no admitidos."))
                if esperados and not rojo_valido:
                    salida["errores"].append(_fallo("ROJO_NO_REPRODUCIDO", "Los casos declarados rojos no fallaron como se esperaba."))
                salida["pruebas_aprobadas"] = verdes and not salida["errores"]
                salida["preparacion_satisfecha"] = etapa == "preparacion" and not salida["errores"] and (verdes or rojo_valido)
                salida["limites"]["pruebas_ejecutadas"] = bool(ejecutados)
                salida["limites"]["descubrimiento_runner"] = bool(salida["verificadores"])
    except Exception as exc:
        salida["errores"].append(_fallo("VERIFICACION_INVALIDA", str(exc) or type(exc).__name__))
    salida["codigo"] = 1 if salida["errores"] else 0
    salida["estado"] = "invalido" if salida["errores"] else "valido"
    salida["huella_informe"] = _hash(salida)
    if destino_permitido:
        try:
            ruta = Path(destino)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with ruta.open("x", encoding="utf-8") as archivo:
                json.dump(salida, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
        except (OSError, ValueError) as exc:
            salida["errores"].append(_fallo("INFORME_NO_GUARDADO", str(exc)))
            salida.update(codigo=1, estado="invalido", pruebas_aprobadas=False, preparacion_satisfecha=False)
            salida.pop("huella_informe", None)
            salida["huella_informe"] = _hash(salida)
    return salida


def evidencia_vigente(raiz, informe, *, arbol="worktree"):
    salida = resultado("evidencia_vigente")
    salida["vigente"] = False
    try:
        if not isinstance(informe, dict) or informe.get("schema") != 1 or informe.get("codigo") != 0:
            raise ValueError("No es un informe satisfactorio del esquema soportado.")
        sin_huella = {k: v for k, v in informe.items() if k != "huella_informe"}
        if informe.get("huella_informe") != _hash(sin_huella):
            raise ValueError("El informe fue alterado o está incompleto.")
        if informe["version_motor"] != _motor():
            raise ValueError("Cambió la versión del núcleo ejecutor.")
        if informe.get("perfil_operacion") == "heimdall-v2":
            _evidencia_vigente_nativa(raiz, informe, arbol)
        else:
            with materializar(raiz, arbol) as copia:
                repo, entradas, autoridad = _entradas(copia, informe["sesion"])
                if repo.config["proyecto"] != informe["proyecto"] or autoridad["huella_acuerdo"] != informe["huella_acuerdo"]:
                    raise ValueError("Proyecto o acuerdo distintos del informe.")
                if informe["etapa"] == "preparacion":
                    if informe["huella_obligaciones"] != huella_obligaciones_materializadas(copia.raiz):
                        raise ValueError("Cambiaron las obligaciones verificadas.")
                elif informe["etapa"] == "entrega":
                    if informe["huella_entradas"] != _hash(entradas):
                        raise ValueError("Cambiaron las entradas verificadas.")
                else:
                    raise ValueError("Etapa desconocida.")
        salida["vigente"] = True
    except Exception as exc:
        salida["errores"].append(_fallo("EVIDENCIA_NO_VIGENTE", str(exc) or type(exc).__name__))
        salida.update(codigo=1, estado="invalido")
    return salida
