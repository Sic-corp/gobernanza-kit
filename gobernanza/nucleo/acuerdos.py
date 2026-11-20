"""Acuerdos y diferencias de F-0104, sin escribir contratos, refs o informes.

La autoridad es un registro cooperativo enlazado con Git. Las huellas no son
firmas del dueño y un dictamen declarado no demuestra por sí solo independencia.
"""

import ast
import base64
import copy
from datetime import datetime, timedelta, timezone
import os
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

from .arboles import ErrorArbol, LectorArbol, _leer_trabajo, _ruta as ruta_git, comprobar_ruta_trabajo
from .convivencia import (
    ACTOR, FICHA, OID, RAICES, RAMA, ErrorConvivencia, RepositorioNativo, _en_ruta_dominio,
    _patron, _secciones, campo, contratos_en, cubre_ruta, frontal, huella_bytes, objeto,
)
from .documentos import Repositorio, json_estricto
from .modelo import coincide, diagnostico, referencia, resultado


class ErrorAcuerdo(ValueError):
    """Acuerdo, árbol u obligaciones no utilizables para esta operación."""


def _materializar(raiz, arbol):
    # Importación diferida para mantener el scaffold independiente del adaptador.
    from .arboles import materializar
    return materializar(raiz, arbol)


def _hash(datos):
    texto = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _commit(raiz, ref):
    if not isinstance(ref, str) or not ref:
        raise ErrorAcuerdo("Se requiere una referencia Git literal no vacía.")
    valor = _git_seguro(raiz, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip().decode("ascii")
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", valor) is None:
        raise ErrorAcuerdo(f"No existe un commit inequívoco para {ref!r}.")
    return valor


def _git_seguro(raiz, *argumentos):
    # La lectura de refs utiliza exactamente el entorno controlado de árboles.
    from .arboles import _git
    try:
        return _git(raiz, *argumentos)
    except ValueError as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _repo(raiz):
    repo = Repositorio(raiz)
    if not repo.cargar_config():
        raise ErrorAcuerdo("Configuración inválida: " + "; ".join(e["mensaje"] for e in repo.errores))
    return repo


def _frontmatter(ruta):
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
        if not lineas or lineas[0] != "---":
            raise ValueError("Falta frontmatter JSON.")
        fin = lineas.index("---", 1)
        datos = json_estricto("\n".join(lineas[1:fin]))
        if not isinstance(datos, dict):
            raise ValueError("El frontmatter debe ser un objeto.")
        return datos, "\n".join(lineas[fin + 1:])
    except (OSError, UnicodeError, ValueError) as exc:
        raise ErrorAcuerdo(f"Documento inválido {ruta.name}: {exc}") from exc


def _ruta(ruta):
    if (not isinstance(ruta, str) or not ruta or "\\" in ruta or "\x00" in ruta
            or PurePosixPath(ruta).is_absolute() or ".." in PurePosixPath(ruta).parts
            or ".git" in PurePosixPath(ruta).parts):
        raise ErrorAcuerdo(f"Ruta autorizante inválida: {ruta!r}.")
    return ruta


def _funcionalidades(valores):
    if (not isinstance(valores, list) or not valores
            or any(not isinstance(v, str) or not re.fullmatch(r"F-\d{4}@r[1-9]\d*", v) for v in valores)):
        raise ErrorAcuerdo("Las funcionalidades del acuerdo requieren referencias F@r explícitas.")
    return sorted(set(valores))


def _autoridad(datos, prosa, sesion):
    if datos.get("schema") == 3:
        if datos.get("tipo") != "sesion" or datos.get("ref") != sesion:
            raise ErrorAcuerdo("La sesión SDD no coincide con el acuerdo requerido.")
        if datos.get("estado") not in {"preparacion", "ejecucion", "pendiente_humana", "lista"}:
            raise ErrorAcuerdo("La fase SDD no habilita el trabajo sobre esta sesión.")
        datos = dict(schema=1, id=sesion, plan=datos.get("plan"), acuerdo=datos.get("mandato"),
                     ejecucion_autorizada=True, funcionalidades=datos.get("funcionalidades"))
        # El cuerpo entero del plan libre forma parte de la captura.
        plan_libre = prosa
        prosa = "<!-- gobernanza:acuerdo -->SDD<!-- /gobernanza:acuerdo -->"
    else:
        plan_libre = None
    if datos.get("id") != sesion or referencia(sesion) != (sesion, None) or not sesion.startswith(("S", "G")):
        raise ErrorAcuerdo("La identidad de la sesión es inválida o no coincide.")
    if type(datos.get("schema")) is not int or datos["schema"] != 1:
        raise ErrorAcuerdo("Se requiere esquema entero 1 en la sesión.")
    if datos.get("ejecucion_autorizada") is not True:
        raise ErrorAcuerdo("Falta la autorización de ejecución de esta sesión.")
    if type(datos.get("plan")) is not int or datos["plan"] < 1:
        raise ErrorAcuerdo("Falta una versión de plan entera positiva.")
    acuerdo = datos.get("acuerdo")
    if not isinstance(acuerdo, dict):
        raise ErrorAcuerdo("Falta el objeto de acuerdo inicial.")
    pedido = acuerdo.get("referencia_pedido")
    if not isinstance(pedido, str) or not pedido.strip():
        raise ErrorAcuerdo("El acuerdo requiere referencia no vacía al pedido real.")
    funciones = _funcionalidades(datos.get("funcionalidades"))
    if _funcionalidades(acuerdo.get("funcionalidades")) != funciones:
        raise ErrorAcuerdo("Las funcionalidades del plan y del acuerdo no coinciden.")
    alcance = acuerdo.get("alcance")
    if not isinstance(alcance, dict):
        raise ErrorAcuerdo("El alcance requiere listas explícitas por tipo de objeto.")
    normalizado = copy.deepcopy(acuerdo)
    normalizado["funcionalidades"] = funciones
    normalizado["alcance"] = {}
    for grupo in ("producto", "pruebas", "documentos", "controles"):
        rutas = alcance.get(grupo)
        if not isinstance(rutas, list):
            raise ErrorAcuerdo(f"alcance.{grupo} debe ser una lista explícita.")
        normalizado["alcance"][grupo] = sorted(set(_ruta(r) for r in rutas))
    if set(alcance) - set(normalizado["alcance"]):
        raise ErrorAcuerdo("El alcance contiene tipos de objeto no soportados.")
    scaffold = acuerdo.get("scaffold")
    if not isinstance(scaffold, list):
        raise ErrorAcuerdo("El scaffold requiere una lista explícita, incluso vacía.")
    for ruta in scaffold:
        _ruta(ruta)
        if ruta.endswith("/") or any(c in ruta for c in "*?["):
            raise ErrorAcuerdo("El scaffold solo admite rutas concretas de archivos.")
        if not any(coincide(ruta, p) for rutas in normalizado["alcance"].values() for p in rutas):
            raise ErrorAcuerdo(f"El scaffold {ruta} está fuera del alcance.")
    normalizado["scaffold"] = sorted(set(scaffold))
    inicio, fin = "<!-- gobernanza:acuerdo -->", "<!-- /gobernanza:acuerdo -->"
    if prosa.count(inicio) != 1 or prosa.count(fin) != 1 or prosa.index(inicio) >= prosa.index(fin):
        raise ErrorAcuerdo("Se requiere una sola sección autorizada delimitada.")
    seccion = prosa.split(inicio, 1)[1].split(fin, 1)[0].strip()
    if not seccion:
        raise ErrorAcuerdo("La sección autorizada no puede estar vacía.")
    autoridad = dict(plan=datos["plan"], funcionalidades=funciones, ejecucion_autorizada=True,
                     acuerdo=normalizado, seccion_acuerdo=seccion if plan_libre is None else plan_libre)
    for campo in ("base_ejecucion", "base"):
        if campo in datos:
            if not isinstance(datos[campo], str) or not datos[campo].strip():
                raise ErrorAcuerdo(f"{campo} requiere una referencia Git no vacía.")
            autoridad[campo] = datos[campo]
    return autoridad


def _localizar(raiz, sesion):
    raiz = Path(raiz)
    repo = _repo(raiz)
    candidatos = []
    for relativa in repo.rutas(repo.config["documentos"]):
        datos, prosa = _frontmatter(raiz / relativa)
        if datos.get("id") == sesion:
            candidatos.append((relativa, _autoridad(datos, prosa, sesion)))
    canonica = f"sdd/registro/{sesion}.md"
    if not candidatos and canonica in repo.rutas(["sdd/registro/*.md"]):
        datos, prosa = _frontmatter(raiz / canonica)
        candidatos.append((canonica, _autoridad(datos, prosa, sesion)))
    if repo.errores:
        raise ErrorAcuerdo("Las rutas documentales no son seguras.")
    if len(candidatos) != 1:
        raise ErrorAcuerdo(f"Se requiere una definición única del acuerdo de {sesion}.")
    return candidatos[0]


def normalizar_autoridad(raiz_materializada, sesion):
    """Proyecta autoridad sin Git para adaptadores que ya poseen una instantánea."""
    ruta, datos = _localizar(raiz_materializada, sesion)
    return dict(ruta_sesion=ruta, datos=datos, huella_acuerdo=_hash(datos))


def _capturar(raiz, sesion, ref_acuerdo, base):
    ref_acuerdo = _commit(raiz, ref_acuerdo)
    base = _commit(raiz, ref_acuerdo if base is None else base)
    try:
        _git_seguro(raiz, "merge-base", "--is-ancestor", base, ref_acuerdo)
    except ErrorAcuerdo as exc:
        raise ErrorAcuerdo("La base de diferencias debe ser antecesora del acuerdo.") from exc
    with _materializar(raiz, ref_acuerdo) as arbol:
        autoridad = normalizar_autoridad(arbol.raiz, sesion)
    for campo in ("base_ejecucion", "base"):
        if campo in autoridad["datos"] and _commit(raiz, autoridad["datos"][campo]) != base:
            raise ErrorAcuerdo(f"La base de captura no coincide con {campo} del acuerdo fuente; pasa explícitamente esa base.")
    captura = dict(schema=1, sesion=sesion, base=base, ref_acuerdo=ref_acuerdo, **autoridad)
    # Integridad ordinaria del registro completo; no constituye una firma.
    captura["huella_captura"] = _hash(captura)
    return captura


def capturar_acuerdo(raiz, sesion, base=None):
    """Captura HEAD; una base declarada anterior requiere argumento explícito.

    huella_captura detecta alteraciones ordinarias de base/ref/ruta y datos. El
    propietario puede recalcularla: no es firma ni defensa frente al dueño.
    """
    try:
        return _capturar(raiz, sesion, "HEAD", base)
    except (ValueError, OSError, TypeError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _coincide(ruta, patrones):
    return any(coincide(ruta, patron) for patron in patrones)


def _salidas(config):
    salidas = config.get("salidas", [])
    if not isinstance(salidas, list):
        raise ErrorAcuerdo("salidas debe ser una lista de rutas.")
    salidas = list(salidas)
    for verificador in config["verificadores"]:
        salidas.extend(verificador.get("salidas_permitidas", []))
    return sorted(set(_ruta(ruta) for ruta in salidas))


def _prefijo(patron):
    partes = []
    for parte in PurePosixPath(patron).parts:
        if any(c in parte for c in "*?["):
            break
        partes.append(parte)
    return tuple(partes)


def _zonas_solapadas(una, otra):
    a, b = _prefijo(una), _prefijo(otra)
    return not a or not b or a[:len(b)] == b or b[:len(a)] == a


def _obligaciones(arbol):
    return huella_obligaciones_materializadas(arbol.raiz)


def huella_obligaciones_materializadas(raiz_materializada):
    """Calcula entradas sobre la copia recibida; nunca vuelve al checkout origen.

    Se enumeran exclusivamente documentos, pruebas y controles declarados. Los
    enlaces internos ligan tanto su destino declarado como sus bytes efectivos.
    """
    raiz = Path(raiz_materializada)
    repo = _repo(raiz)
    config = repo.config
    entradas = ["gobernanza/config.json", "sdd/registro/*.md", *config["documentos"],
                *config["raices"]["pruebas"], *config["raices"]["controles"]]
    salidas = _salidas(config)
    if any(_zonas_solapadas(salida, entrada) for salida in salidas for entrada in entradas):
        raise ErrorAcuerdo("Las salidas no pueden solaparse con documentos, pruebas o controles.")
    seleccion = {}
    for ruta in repo.rutas(entradas):
        archivo = repo.segura(ruta)
        if archivo is None:
            continue
        try:
            huella = hashlib.sha256(archivo.read_bytes()).hexdigest()
            modo = "120000" if archivo.is_symlink() else "100755" if archivo.stat().st_mode & 0o111 else "100644"
            destino = str(archivo.readlink()) if archivo.is_symlink() else None
        except (OSError, UnicodeError) as exc:
            raise ErrorAcuerdo(f"No se puede leer la obligación {ruta}: {exc}") from exc
        if _coincide(ruta, [*config["documentos"], "sdd/registro/*.md"]):
            datos, prosa = _frontmatter(archivo)
            if (datos.get("schema") == 3 and datos.get("tipo") == "sesion"
                    and datos.get("mandato") and datos.get("estado") in {"preparacion", "ejecucion", "pendiente_humana", "lista"}):
                huella = _hash(_autoridad(datos, prosa, datos["ref"]))
            identidad = datos.get("id", "")
            if isinstance(identidad, str) and re.fullmatch(r"[SG]\d{2}-\d{2}", identidad) and "acuerdo" in datos:
                huella = _hash(_autoridad(datos, prosa, identidad))
        seleccion[ruta] = dict(sha256=huella, modo=modo, destino=destino)
    if repo.errores:
        raise ErrorAcuerdo("Entradas de obligaciones inválidas: " + "; ".join(e["mensaje"] for e in repo.errores))
    return _hash(seleccion)


def huella_obligaciones(raiz, arbol="worktree"):
    """Liga preparación a pruebas, contratos y controles, incluyendo config entera."""
    try:
        with _materializar(raiz, arbol) as vista:
            return _obligaciones(vista)
    except (ValueError, OSError, TypeError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _vinculos(texto, arbol):
    """Conserva cada comentario junto al mismo caso, incluso al insertar casos."""
    lineas, vinculos = texto.splitlines(), {}
    for clase in arbol.body:
        if not isinstance(clase, ast.ClassDef):
            continue
        for metodo in clase.body:
            if not isinstance(metodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            inicio = min([metodo.lineno] + [d.lineno for d in metodo.decorator_list])
            comentario = lineas[inicio - 2].strip() if inicio > 1 else ""
            if comentario.startswith("# gobernanza-test:"):
                vinculos[(clase.name, metodo.name)] = comentario
    return vinculos


def _adicion_pura(antes, despues):
    """Acepta casos añadidos sin reemplazar nodos previos ni sus metadatos.

    Cambios no demostrables (imports, fixtures, aserciones o decoradores) requieren
    dictamen; esta comparación no promete equivalencia semántica general.
    """
    try:
        viejo, nuevo = ast.parse(antes), ast.parse(despues)
    except (SyntaxError, ValueError):
        return False
    agregado = False

    def nodo(n):
        return ast.dump(n, include_attributes=False)

    def cuerpo(viejos, nuevos, dentro_clase=False):
        nonlocal agregado
        if len(nuevos) < len(viejos):
            return False
        nombres = {getattr(n, "name", None) for n in viejos}
        posicion = 0

        def agregar(extra):
            nonlocal agregado
            if getattr(extra, "name", None) in nombres:
                return False
            if dentro_clase:
                if not isinstance(extra, (ast.FunctionDef, ast.AsyncFunctionDef)) or not extra.name.startswith("test_"):
                    return False
            elif not isinstance(extra, ast.ClassDef) or any(not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) or not m.name.startswith("test_") for m in extra.body):
                return False
            nombres.add(extra.name)
            agregado = True
            return True

        for anterior in viejos:
            while posicion < len(nuevos):
                candidato = nuevos[posicion]
                misma_clase = isinstance(anterior, ast.ClassDef) and isinstance(candidato, ast.ClassDef) and anterior.name == candidato.name
                if misma_clase or nodo(anterior) == nodo(candidato):
                    break
                if not agregar(candidato):
                    return False
                posicion += 1
            if posicion >= len(nuevos):
                return False
            actual = nuevos[posicion]
            if isinstance(anterior, ast.ClassDef) and isinstance(actual, ast.ClassDef) and anterior.name == actual.name:
                a, b = copy.deepcopy(anterior), copy.deepcopy(actual)
                a.body, b.body = [], []
                if nodo(a) != nodo(b) or not cuerpo(anterior.body, actual.body, True):
                    return False
            elif nodo(anterior) != nodo(actual):
                return False
            posicion += 1
        for extra in nuevos[posicion:]:
            if not agregar(extra):
                return False
        return True

    if not cuerpo(viejo.body, nuevo.body) or not agregado:
        return False
    anteriores, actuales = _vinculos(antes, viejo), _vinculos(despues, nuevo)
    return all(actuales.get(caso) == comentario for caso, comentario in anteriores.items())


def _dictamen_valido(dictamenes, cambio):
    if not isinstance(dictamenes, (list, tuple)):
        return False
    return any(isinstance(d, dict) and d.get("ruta") == cambio["ruta"]
               and d.get("base_sha256") == cambio["base_sha256"]
               and d.get("nuevo_sha256") == cambio["nuevo_sha256"]
               and isinstance(d.get("revisor"), str) and bool(d["revisor"].strip())
               and d.get("decision") == "conservar_obligacion"
               and isinstance(d.get("motivo"), str) and bool(d["motivo"].strip())
               for d in dictamenes)


def _destinos_pruebas(arbol, patrones):
    """Un fixture aceptado protege también su destino efectivo dentro del árbol."""
    destinos = []
    for ruta in arbol.archivos:
        if not _coincide(ruta, patrones):
            continue
        archivo = arbol.raiz / ruta
        if archivo.is_symlink():
            try:
                destinos.append(archivo.resolve().relative_to(arbol.raiz.resolve()).as_posix())
            except (OSError, ValueError, RuntimeError) as exc:
                raise ErrorAcuerdo(f"Destino de prueba no utilizable: {ruta}") from exc
    return destinos


def validar_cambios(raiz, sesion, acuerdo, *, arbol="worktree", fase="preparacion", preparacion=None, dictamenes=()):
    """Diagnostica cambios de un árbol materializado contra un acuerdo capturado."""
    errores, cambios = [], []

    def error(codigo, ruta, mensaje, requisito="Acuerdo, alcance y fase vigentes",
              resolucion="Corrige el cambio o registra la decisión independiente aplicable."):
        errores.append(diagnostico(codigo, ruta, requisito, mensaje, resolucion))

    huella = acuerdo.get("huella_acuerdo", "") if isinstance(acuerdo, dict) else ""
    try:
        if fase not in {"preparacion", "ejecucion", "entrega"}:
            raise ErrorAcuerdo("Fase inválida; usa preparacion, ejecucion o entrega.")
        if not isinstance(acuerdo, dict) or acuerdo.get("sesion") != sesion or type(acuerdo.get("schema")) is not int or acuerdo["schema"] != 1:
            raise ErrorAcuerdo("Falta un acuerdo capturado para esta sesión.")
        for campo in ("base", "ref_acuerdo", "ruta_sesion", "huella_acuerdo", "huella_captura"):
            if not isinstance(acuerdo.get(campo), str) or not acuerdo[campo]:
                raise ErrorAcuerdo(f"El acuerdo no contiene {campo} válido.")
        contenido_captura = {k: v for k, v in acuerdo.items() if k != "huella_captura"}
        if _hash(contenido_captura) != acuerdo["huella_captura"]:
            raise ErrorAcuerdo("La integridad de la captura cambió; conserva el registro capturado sin editar base, ref, ruta o datos.")
        from .registro_sdd import auditar
        errores.extend(auditar(raiz, arbol))
        autorizado = _capturar(raiz, sesion, acuerdo["ref_acuerdo"], acuerdo["base"])
        if acuerdo != autorizado:
            raise ErrorAcuerdo("La captura no corresponde al acuerdo conservado en ref_acuerdo.")
        with _materializar(raiz, acuerdo["ref_acuerdo"]) as fuente, _materializar(raiz, acuerdo["base"]) as base, _materializar(raiz, arbol) as destino:
            config = _repo(fuente.raiz).config
            config_base = _repo(base.raiz).config
            config_destino = _repo(destino.raiz).config
            try:
                datos, prosa = _frontmatter(destino.raiz / acuerdo["ruta_sesion"])
                if _autoridad(datos, prosa, sesion) != acuerdo["datos"]:
                    error("ACUERDO_ALTERADO", acuerdo["ruta_sesion"], "El árbol cambia los datos autorizantes o la sección del acuerdo.")
            except ErrorAcuerdo as exc:
                error("ACUERDO_ALTERADO", acuerdo["ruta_sesion"], str(exc))
            obligaciones = _obligaciones(destino)
            alcance = acuerdo["datos"]["acuerdo"]["alcance"]
            scaffold = acuerdo["datos"]["acuerdo"]["scaffold"]
            permitidas = [p for rutas in alcance.values() for p in rutas]
            salidas = _salidas(config)
            pruebas_autorizadas = alcance["pruebas"] + config["raices"]["pruebas"] + config_base["raices"]["pruebas"]
            pruebas_autorizadas += _destinos_pruebas(base, pruebas_autorizadas)
            pruebas = pruebas_autorizadas + config_destino["raices"]["pruebas"]
            controles = alcance["controles"] + config["raices"]["controles"] + config_base["raices"]["controles"]
            producto = alcance["producto"] + config["raices"]["solucion"] + config_base["raices"]["solucion"]
            requiere_producto = False
            seleccion_anterior = {k: config_base.get(k) for k in ("verificadores",)}
            seleccion_actual = {k: config_destino.get(k) for k in ("verificadores",)}
            seleccion_anterior["pruebas"] = config_base["raices"]["pruebas"]
            seleccion_actual["pruebas"] = config_destino["raices"]["pruebas"]
            for ruta in sorted(base.archivos.keys() | destino.archivos.keys()):
                anterior, nuevo = base.archivos.get(ruta), destino.archivos.get(ruta)
                if anterior == nuevo:
                    continue
                cambio = dict(ruta=ruta, tipo="agregado" if anterior is None else "borrado" if nuevo is None else "modificado",
                              base_sha256=anterior["sha256"] if anterior else None,
                              nuevo_sha256=nuevo["sha256"] if nuevo else None)
                cambios.append(cambio)
                if not _coincide(ruta, permitidas + salidas):
                    error("FUERA_ALCANCE", ruta, "La ruta anterior o nueva no pertenece al alcance autorizado.")
                es_prueba = _coincide(ruta, pruebas)
                es_control = _coincide(ruta, controles)
                if es_control and not sesion.startswith("G"):
                    error("CONTROL_SIN_SESION_G", ruta, "Los controles requieren una sesión de gobernanza.")
                if _coincide(ruta, producto) and not _coincide(ruta, pruebas_autorizadas) and not es_control and ruta not in scaffold:
                    requiere_producto = True
                sensible = bool(anterior and es_prueba)
                if sensible and nuevo and ruta.endswith(".py") and anterior["modo"] == nuevo["modo"]:
                    sensible = not _adicion_pura((base.raiz / ruta).read_text(encoding="utf-8"), (destino.raiz / ruta).read_text(encoding="utf-8"))
                if ruta == "gobernanza/config.json" and seleccion_anterior != seleccion_actual:
                    sensible = True
                if sensible and not _dictamen_valido(dictamenes, cambio):
                    error("PRUEBA_SENSIBLE", ruta, "Una obligación aceptada cambió sin dictamen concreto enlazado al contenido.",
                          "Conservar pruebas, fixtures y selección aceptados", "Preserva la obligación o aporta dictamen independiente con hashes anterior y nuevo.")
            if requiere_producto:
                if fase == "preparacion":
                    error("PRODUCTO_ANTES_PREPARACION", ".", "La preparación solo permite documentos, pruebas y scaffold explícito.")
                if (not isinstance(preparacion, dict) or preparacion.get("preparacion_satisfecha") is not True
                        or preparacion.get("huella_acuerdo") != huella
                        or preparacion.get("huella_obligaciones") != obligaciones):
                    error("PREPARACION_NO_VIGENTE", ".", "Falta evidencia de preparación satisfecha para este acuerdo y estas obligaciones.",
                          "Preparación real ligada al contenido", "Ejecuta los verificadores de preparación y conserva su evidencia vigente.")
    except (ValueError, OSError, TypeError, KeyError) as exc:
        error("ACUERDO_INVALIDO", ".", str(exc))
    salida = resultado("validar_cambios", errores)
    salida.update(cambios=cambios, fase=fase, huella_acuerdo=huella)
    return salida


def _identidad_nativa(dato, patron, nombre):
    if not isinstance(dato, str) or re.fullmatch(patron, dato) is None or dato in {".", ".."}:
        raise ErrorAcuerdo(f"Identidad nativa inválida para {nombre}: {dato!r}.")
    return dato


def _ancestro_nativo(repo, ancestro, punta):
    return repo.git("merge-base", "--all", ancestro, punta).decode("ascii").split() == [ancestro]


def _ruta_presentada(plan, relativo):
    if (not isinstance(relativo, str) or not relativo or "\\" in relativo or relativo.startswith("/")
            or any(caracter in relativo for caracter in "?#:")):
        raise ErrorAcuerdo(f"Documento de aprobación inseguro: {relativo!r}.")
    ruta = ruta_git(posixpath.normpath(posixpath.join(posixpath.dirname(plan["ruta"]), relativo)))
    anexo = plan["estado_modulo"].removesuffix("estado.md") + "anexos/"
    if not ruta.startswith(anexo):
        raise ErrorAcuerdo(f"Documento presentado fuera de los anexos del módulo: {ruta}.")
    return ruta


def _cotejar_relevo(repo, plan, entrada, actor, tx, punta):
    relevo = entrada.get("relevo")
    if actor == tx and relevo is None:
        return None
    if not isinstance(relevo, dict):
        raise ErrorAcuerdo("El actor receptor requiere un registro de relevo anclado.")
    saliente = _identidad_nativa(relevo.get("actor_saliente"), ACTOR, "actor saliente")
    ref = _identidad_nativa(relevo.get("ref"), OID, "punta de relevo")
    if (saliente == actor or relevo.get("actor_receptor") != actor or relevo.get("transaccion") != tx
            or not _ancestro_nativo(repo, ref, punta)):
        raise ErrorAcuerdo("El relevo no corresponde al actor, transacción o punta del escritor.")
    fuente = relevo.get("fuente")
    modulo = plan["estado_modulo"].removesuffix("estado.md")
    if (not isinstance(fuente, str) or not fuente.startswith((modulo + "anexos/", modulo + "sesiones/"))):
        raise ErrorAcuerdo("Registro de relevo fuera del módulo.")
    repo_punta = repo.en_arbol(punta, historico=True)
    datos = repo_punta.texto(fuente)
    literales = {saliente, actor, tx, ref}
    if not all(f"`{literal}`" in datos for literal in literales):
        raise ErrorAcuerdo("El documento de relevo no liga las dos identidades, transacción y punta.")
    if repo_punta.fuente(fuente).blob != repo.fuente(fuente).blob:
        raise ErrorAcuerdo("La fuente del relevo tiene cambios locales.")
    plan_relevo = repo.en_arbol(ref, historico=True).plan(plan["folio"])
    if _campos_acuerdo_nativo(plan_relevo) != _campos_acuerdo_nativo(plan):
        raise ErrorAcuerdo("El relevo intenta transferir versión, base o alcance distintos.")
    # Una cadena posterior debe conservar al receptor previo como saliente.
    if saliente != tx:
        anterior = relevo.get("anterior")
        if not isinstance(anterior, dict) or anterior.get("ref") == ref:
            raise ErrorAcuerdo("Falta la cadena de relevo desde el actor de origen.")
        _cotejar_relevo(repo, plan, {"relevo": anterior}, saliente, tx, ref)
    return dict(relevo, sha256=repo_punta.fuente(fuente).sha256)


def _identidad_plan_nativo(plan):
    return {clave: plan[clave] for clave in (
        "folio", "proyecto", "perfil", "dominio", "modulo", "ruta", "evidencia",
        "alcance", "contratos", "funcionalidades", "version",
    )}


def _campos_acuerdo_nativo(plan):
    return {clave: plan[clave] for clave in (
        "folio", "proyecto", "perfil", "dominio", "version", "modulo", "ruta",
        "evidencia", "alcance", "contratos", "funcionalidades", "base", "cita", "aprobaciones",
    )}


def comprobar_autoridad_nativa(repo, folio, entrada, *, fase="trabajo"):
    """Coteja las entradas documentales en Git. La decisión humana conserva su fuente."""
    try:
        return _autoridad_nativa(repo, folio, entrada, fase)
    except (ErrorArbol, ErrorConvivencia, OSError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _autoridad_nativa(repo, folio, entrada, fase):
    if not isinstance(repo, RepositorioNativo) or not isinstance(entrada, dict):
        raise ErrorAcuerdo("Se requieren repositorio nativo y entrada documental.")
    actor = _identidad_nativa(entrada.get("actor"), ACTOR, "actor")
    tx = _identidad_nativa(entrada.get("transaccion"), ACTOR, "transacción")
    ref = _identidad_nativa(entrada.get("ref_acuerdo"), OID, "ref de acuerdo")
    base = _identidad_nativa(entrada.get("base"), OID, "base aprobada")
    plan = repo.plan(folio)
    rama = f"codex/{folio}/{tx}"
    rama_fuente = repo.commit_ref("refs/heads/" + rama)
    seleccion = repo.commit or repo.head
    if fase == "integracion":
        if (entrada.get("rama_fuente", rama) != rama or seleccion != rama_fuente
                or (repo.rama != rama and (repo.rama != "main" or repo.commit is None))):
            raise ErrorAcuerdo(f"El árbol no corresponde a la punta exacta de {rama}.")
    elif repo.rama != rama or not _ancestro_nativo(repo, seleccion, rama_fuente):
        raise ErrorAcuerdo(f"El checkout y árbol no corresponden al escritor exclusivo de {rama}.")
    if (plan["estado"] != "Activo" or (plan["transaccion"] is not None and plan["transaccion"] != tx)
            or plan["version"] != entrada.get("version") or plan["cita"] != entrada.get("cita")
            or not plan["cita"] or plan["base"] != base):
        raise ErrorAcuerdo("Aprobación, versión, estado, transacción o base ajenos al plan Activo.")
    procedencia = procedencia_acuerdo_nativo(repo, folio, ref_acuerdo=ref, base=base, transaccion=tx)
    documento = repo.en_arbol(procedencia["ref_activo"], historico=True)
    fuente = procedencia["plan"]
    if entrada.get("documento_aprobado") is not None:
        presentado = entrada["documento_aprobado"]
        if not isinstance(presentado, dict):
            raise ErrorAcuerdo("Entrada de documento presentado inválida.")
        ruta = presentado.get("ruta")
        sha = presentado.get("sha256")
        texto = documento.texto(fuente["ruta"])
        if (not isinstance(ruta, str) or not ruta.startswith(fuente["estado_modulo"].removesuffix("estado.md") + "anexos/")
                or not isinstance(sha, str) or f"`{sha}`" not in texto
                or documento.fuente(ruta).sha256 != sha or repo.fuente(ruta).sha256 != sha):
            raise ErrorAcuerdo("La fuente presentada no coincide con la aprobación guardada.")
    relevo = _cotejar_relevo(repo, plan, entrada, actor, tx, seleccion)
    return dict(procedencia, actor=actor, relevo=relevo,
                autoridad_cotejada=True, limites={"autoridad": False})


def procedencia_acuerdo_nativo(repo, folio, *, ref_acuerdo, base, transaccion):
    """Reconstruye la huella desde Git para comparar un informe de otra fase."""
    try:
        return _procedencia_acuerdo_nativo(repo, folio, ref_acuerdo, base, transaccion)
    except (ErrorArbol, ErrorConvivencia, OSError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _procedencia_acuerdo_nativo(repo, folio, ref_acuerdo, base, transaccion):
    if not isinstance(repo, RepositorioNativo):
        raise ErrorAcuerdo("Se requiere repositorio nativo para reconstruir el acuerdo.")
    transaccion = _identidad_nativa(transaccion, ACTOR, "transacción")
    ref = _identidad_nativa(ref_acuerdo, OID, "ref de acuerdo")
    base = _identidad_nativa(base, OID, "base aprobada")
    plan = repo.plan(folio)
    seleccion = repo.commit or repo.head
    if (plan["estado"] != "Activo" or plan["base"] != base or not plan["cita"]
            or plan["transaccion"] not in (None, transaccion)):
        raise ErrorAcuerdo("El acuerdo anclado difiere del folio, su base o transacción.")
    if not _ancestro_nativo(repo, base, ref) or not _ancestro_nativo(repo, ref, seleccion):
        raise ErrorAcuerdo("La base y la ref de acuerdo deben preceder al árbol de la transacción.")
    documento = repo.en_arbol(ref, historico=True)
    fuente = documento.plan(folio)
    borrador = None
    if fuente["estado"] == "Borrador":
        borrador = fuente
        if _identidad_plan_nativo(borrador) != _identidad_plan_nativo(plan):
            raise ErrorAcuerdo("La activación alteró la identidad o alcance presentado del Borrador.")
        cadena = repo.git("rev-list", "--first-parent", "--reverse", f"{ref}..{seleccion}").decode("ascii").split()
        if not cadena:
            raise ErrorAcuerdo("Falta el guardado de activación del Borrador.")
        activacion = cadena[0]
        padres = repo.git("rev-list", "--parents", "-n", "1", activacion).decode("ascii").split()[1:]
        if padres != [ref]:
            raise ErrorAcuerdo("El primer guardado de activación no procede del Borrador exacto.")
        documento = repo.en_arbol(activacion, historico=True)
        fuente = documento.plan(folio)
    if fuente["estado"] != "Activo" or _campos_acuerdo_nativo(fuente) != _campos_acuerdo_nativo(plan):
        raise ErrorAcuerdo("El acuerdo guardado difiere de la autoridad aplicable.")
    aprobacion = next(a for a in fuente["aprobaciones"] if a["version"] == fuente["version"])
    if aprobacion.get("ambigua"):
        raise ErrorAcuerdo("La cita literal de aprobación de esta versión es ambigua.")
    if "documento" in aprobacion:
        ruta = _ruta_presentada(fuente, aprobacion["documento"])
        documento_aprobado = documento.fuente(ruta)
        if (documento_aprobado.sha256 != aprobacion["sha256"]
                or repo.fuente(ruta).sha256 != documento_aprobado.sha256):
            raise ErrorAcuerdo(f"El texto presentado no corresponde a la huella aprobada: {ruta}.")
    procedencia = {
        "schema": 1, "transaccion": transaccion, "base": base, "ref_acuerdo": ref,
        "ruta": fuente["ruta"], "blob": fuente["blob"], "aprobacion": aprobacion,
        "ref_activo": documento.commit, "blob_borrador": borrador["blob"] if borrador else None,
        "plan": plan,
    }
    procedencia["huella_acuerdo"] = _hash({
        "plan": _campos_acuerdo_nativo(fuente), "blob": fuente["blob"], "ref_acuerdo": ref,
        "ref_activo": documento.commit, "blob_borrador": borrador["blob"] if borrador else None,
        "transaccion": transaccion, "proyecto": repo.proyecto, "perfil": repo.perfil,
    })
    return procedencia


def _git_worktrees_nativos(repo):
    sal = repo.git("worktree", "list", "--porcelain", "-z")
    arboles = {}
    for bloque in sal.split(b"\0\0"):
        if not bloque:
            continue
        datos = {}
        for linea in bloque.split(b"\0"):
            clave, _, valor = linea.partition(b" ")
            if clave in datos:
                raise ErrorAcuerdo("Inventario Git de worktrees ambiguo.")
            datos[clave] = os.fsdecode(valor)
        ref = datos.get(b"branch")
        if not ref or not ref.startswith("refs/heads/codex/"):
            if b"worktree" not in datos:
                raise ErrorAcuerdo("Inventario Git de worktrees ilegible.")
            if ref != "refs/heads/main":
                continue
        ruta = datos.get(b"worktree")
        if not ruta or not Path(ruta).is_absolute() or ref in arboles or b"prunable" in datos:
            raise ErrorAcuerdo(f"Inventario Git sin worktree atribuible a {ref}.")
        raiz = Path(ruta).resolve(strict=True)
        arboles[ref] = (raiz, _identidad_nativa(datos.get(b"HEAD"), OID, "HEAD de worktree"))
    return arboles


def _git_refs_nativas(repo):
    lineas = repo.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/codex/").decode().splitlines()
    refs = {}
    for linea in lineas:
        ref, _, sha = linea.partition(" ")
        if not ref.startswith("refs/heads/codex/") or ref in refs:
            raise ErrorAcuerdo(f"Inventario Git de refs ambiguo: {linea!r}.")
        refs[ref] = _identidad_nativa(sha, OID, "punta de ref")
    return refs


def _cambios_fuente(base, actual):
    diferencia = {ruta for ruta in set(base.entradas) | set(actual.entradas)
                  if base.entradas.get(ruta) != actual.entradas.get(ruta)}
    if actual.arbol != "worktree":
        return diferencia
    for ruta in actual.rutas:
        original = base.entradas.get(ruta)
        if original is None:
            intervencion = r"(?:.*/)?gobernanza/sesiones/intervenciones/[^/]+\.jsonl"
            if ruta in actual.entradas or re.fullmatch(intervencion, ruta) is None:
                diferencia.add(ruta)
            continue
        imagen = _leer_trabajo(actual.raiz, ruta)
        if (imagen is None or imagen[0] != original[0]
                or actual.blob(ruta, imagen[1], longitud=len(original[1])) != original[1]):
            diferencia.add(ruta)
    return diferencia


def _permiso_vivo(repo, folio, rama, ref, puntas):
    for raiz in puntas:
        ruta_runtime = raiz / f".{repo.proyecto}" / "runtime" / "integration"
        rutas_permiso = []
        for directorio in (raiz / f".{repo.proyecto}", ruta_runtime.parent, ruta_runtime):
            if directorio.is_symlink():
                raise ErrorAcuerdo(f"Inventario de permisos enlazado: {directorio}.")
        if ruta_runtime.exists():
            for actor in ruta_runtime.iterdir():
                if actor.is_symlink():
                    raise ErrorAcuerdo(f"Inventario de permisos enlazado: {actor}.")
                if actor.is_file():
                    continue
                objetivo = actor / folio
                if objetivo.is_symlink():
                    raise ErrorAcuerdo(f"Inventario de permisos enlazado: {objetivo}.")
                rutas_permiso.extend((actor / f"{repo.proyecto}.json",
                                       objetivo / f"{repo.proyecto}.json"))
        for ruta in rutas_permiso:
            imagen = _leer_trabajo(raiz, str(ruta.relative_to(raiz)))
            if imagen is None:
                continue
            if imagen[0] not in {"100644", "100755"}:
                raise ErrorAcuerdo(f"Inventario de permisos no regular: {ruta}.")
            permiso = objeto(imagen[1], str(ruta))
            identidad_folio = permiso.get("folio")
            if not isinstance(identidad_folio, str):
                raise ErrorAcuerdo(f"Permiso de integración sin folio atribuible: {ruta}.")
            if identidad_folio != folio:
                if ruta.parent.name == folio:
                    raise ErrorAcuerdo(f"Inventario de permisos con folio contradictorio: {ruta}.")
                continue
            actor = ruta.parent.parent.name if ruta.parent.name == folio else ruta.parent.name
            esperado = {
                "project_id": repo.proyecto, "profile_version": 2, "schema_version": 1,
                "session_id": actor, "root": str(repo.comun), "git_common_dir": str(repo.comun),
                "integrator_root": str(raiz),
            }
            if (any(permiso.get(c) != v for c, v in esperado.items())
                    or not isinstance(permiso.get("source_sha"), str)
                    or re.fullmatch(OID, permiso["source_sha"]) is None
                    or permiso.get("branch") != rama
                    or not _ancestro_nativo(repo, permiso["source_sha"], ref)):
                raise ErrorAcuerdo(f"Permiso de integración ajeno o alterado para {folio}: {ruta}.")
            fase = permiso.get("phase")
            if fase not in {"approved", "merged", "suite-failed", "suite-green", "reverted",
                            "resolved", "complete"}:
                raise ErrorAcuerdo(f"Permiso de integración sin fase nativa reconocible: {ruta}.")
            if fase not in {"complete", "resolved"}:
                return True
            if fase == "complete":
                cierre = _identidad_nativa(permiso.get("closure_sha"), OID, "commit de cierre")
                main = repo.commit_ref("refs/heads/main")
                if not _ancestro_nativo(repo, cierre, main):
                    raise ErrorAcuerdo(f"El permiso terminal de {folio} carece de cierre integrado.")
    return False


def _reversion_nativa(repo, fuente, main):
    merges = repo.git("rev-list", "--first-parent", "--merges", "--parents", main).decode("ascii").splitlines()
    for linea in merges:
        merge, anterior, *lados = linea.split()
        if not any(_ancestro_nativo(repo, fuente, lado) for lado in lados):
            continue
        if _ancestro_nativo(repo, fuente, anterior):
            continue
        restaurado = repo.git("rev-parse", "--verify", f"{anterior}^{{tree}}").decode("ascii").strip()
        posteriores = repo.git(
            "log", "--first-parent", "--no-notes", "--format=%T", f"{merge}..{main}", "--",
        ).decode("ascii").split()
        return restaurado in posteriores
    return False


def _cerrado_en_main(repo, principal, plan, rama, ref, integrada, pendientes, raices):
    if not integrada or pendientes:
        return False
    candidatos = [ruta for folio, ruta in principal.rutas_planes() if folio == plan["folio"]]
    if len(candidatos) != 1 or candidatos[0] != plan["ruta"]:
        return False
    texto = principal.texto(candidatos[0])
    if (campo(texto, "Estado") != "Completado" or campo(texto, "Versión") != plan["version"]
            or campo(texto, "Módulo") != plan["modulo"]):
        return False
    if plan["evidencia"]:
        principal.leer(plan["evidencia"])
        principal.leer(plan["estado_modulo"])
    return not (_permiso_vivo(repo, plan["folio"], rama, ref, raices)
                or _reversion_nativa(repo, ref, principal.commit))


def _solape_contratos(repo, plan, destinos, otra_fuente, otro):
    def requisitos(origen, plan_):
        rutas = set(plan_["contratos"])
        rutas.update(origen.ficha(ref)["ruta"] for ref in plan_["funcionalidades"])
        return rutas

    propios = requisitos(repo, plan)
    ajenos = requisitos(otra_fuente, otro)
    return next((contrato for contrato in sorted(ajenos)
                 if any(cubre_ruta(destino, contrato) for destino in destinos)), None) or next(
        (contrato for contrato in sorted(propios)
         if any(cubre_ruta(patron, contrato) for patron in otro["alcance"])), None)


def _lector_claim(repo, lector, rama, head):
    # El inventario examina el alcance de la ref bajo el perfil actual.
    # Un antecedente legítimo puede preceder al pin o a sus anexos.
    fuente = copy.copy(repo)
    fuente.raiz, fuente.lector = lector.raiz, lector
    fuente.arbol, fuente.commit, fuente.head, fuente.rama = lector.arbol, lector.commit, head, rama
    fuente._lector_head = None
    fuente._historicos = {}
    return fuente


def _plan_claim(repo, folio, ruta):
    texto = repo.texto(ruta)
    cabecera = texto.split("\n##", 1)[0]
    modulo, estado, version = (campo(cabecera, campo_) for campo_ in ("Módulo", "Estado", "Versión"))
    if (campo(cabecera, "Proyecto") != repo.proyecto
            or not re.search(rf"^# .*\b{folio}\b", cabecera, re.MULTILINE)
            or not modulo or not re.fullmatch(r"[a-z0-9-]+", modulo)
            or not version or not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", version)
            or estado not in {"Activo", "Borrador", "Completado"}):
        raise ErrorAcuerdo(f"Plan de claim ilegible para {folio}: {ruta}.")
    dominio = folio[0]
    secciones = _secciones(texto)
    alcances = [contenido for numero, _, contenido in secciones if numero == 3]
    if len(alcances) != 1:
        raise ErrorAcuerdo(f"Alcance de claim ambiguo en {ruta}.")
    alcance = [_patron(p, dominio, repo.raices_solucion, ruta)
               for p in re.findall(r"`([^`\n]+)`", alcances[0])]
    if not alcance:
        raise ErrorAcuerdo(f"Alcance de claim vacío en {ruta}.")
    prefijo = "gobernanza/sdd/" if dominio == "G" else "sdd/"
    referencias = "\n".join(c for n, _, c in secciones if n == 2)
    contratos = contratos_en(referencias, ruta)
    if not contratos or any(not p.startswith(prefijo) for p in contratos):
        raise ErrorAcuerdo(f"Contratos del claim fuera del dominio de {folio}: {ruta}.")
    fichas = campo(cabecera, "Funcionalidades") or ""
    evidencia = campo(cabecera, "Evidencia")
    estado_modulo = f"{RAICES[dominio]}/modulos/{modulo}/estado.md"
    return dict(folio=folio, version=version, estado=estado, modulo=modulo, ruta=ruta,
                alcance=alcance, contratos=sorted(contratos), evidencia=evidencia,
                estado_modulo=estado_modulo, transaccion=campo(cabecera, "ID de sesión"),
                funcionalidades=[f.strip().strip("`") for f in fichas.split(",") if f.strip()])


def _claims_nativos(repo, plan, tx, rutas, *, rama_fuente=None):
    referencias = _git_refs_nativas(repo)
    worktrees = _git_worktrees_nativos(repo)
    main = repo.commit_ref("refs/heads/main")
    principal = repo.en_arbol(main, historico=True)
    raiz_lista = sorted({raiz for raiz, _ in worktrees.values()} | {repo.raiz})
    cambios_propios = rutas or plan["alcance"]
    inventario = []
    for ref, sha in referencias.items():
        rama = ref.removeprefix("refs/heads/")
        if rama == repo.rama:
            if worktrees.get(ref) != (repo.raiz, repo.head):
                raise ErrorAcuerdo(f"Inventario sin escritor exclusivo para {rama}.")
            continue
        if rama == rama_fuente:
            if sha != repo.commit or (ref in worktrees and worktrees[ref][1] != sha):
                raise ErrorAcuerdo(f"Inventario con punta fuente divergente: {rama}.")
            continue
        match = re.fullmatch(RAMA, rama)
        if not match:
            raise ErrorAcuerdo(f"No se puede atribuir una ref del inventario: {rama}.")
        atribucion, otro_tx = match.groups()
        integrada = _ancestro_nativo(repo, sha, main)
        casilla = worktrees.get(ref)
        guardada = LectorArbol(repo.raiz, sha)
        captura = _lector_claim(repo, guardada, rama, sha)
        pendientes = set()
        if casilla:
            raiz, cabeza = casilla
            if sha != cabeza:
                raise ErrorAcuerdo(f"Inventario divergente en {rama}.")
            lector = LectorArbol(raiz, "worktree")
            pendientes = _cambios_fuente(captura.lector, lector)
            if pendientes:
                captura = _lector_claim(repo, lector, rama, sha)
        if atribucion == "PLANIFICACION" and otro_tx == tx:
            if pendientes or not _ancestro_nativo(repo, sha, repo.commit if rama_fuente else repo.head):
                raise ErrorAcuerdo(f"La planificación de la transacción diverge o conserva pendientes: {rama}.")
            continue

        candidatos = captura.rutas_planes()
        if atribucion == "PLANIFICACION":
            diferencias = repo.git("merge-base", "--all", sha, main).decode("ascii").split()
            if len(diferencias) != 1:
                raise ErrorAcuerdo(f"Base de planificación ambigua: {rama}.")
            base_planificacion = LectorArbol(repo.raiz, diferencias[0])
            diferencia = _cambios_fuente(base_planificacion, guardada)
            candidatos = [(folio, ruta) for folio, ruta in candidatos
                          if ruta in diferencia | pendientes
                          or campo(captura.texto(ruta), "ID de sesión") == otro_tx
                          or (integrada and casilla is None and campo(captura.texto(ruta), "Estado") in {"Activo", "Borrador"})]
            if integrada and not candidatos and not pendientes:
                continue
        else:
            candidatos = [(folio, ruta) for folio, ruta in candidatos if folio == atribucion]
        if len(candidatos) != 1 and not (integrada and casilla is None and candidatos):
            raise ErrorAcuerdo(f"No se puede atribuir un plan único del inventario a {rama}.")
        for folio, ruta in candidatos:
            otro = _plan_claim(captura, folio, ruta)
            if otro["transaccion"] is not None and otro["transaccion"] != otro_tx:
                raise ErrorAcuerdo(f"La transacción del plan {folio} no corresponde a {rama}.")
            if _cerrado_en_main(repo, principal, otro, rama, sha, integrada, pendientes, raiz_lista):
                inventario.append({"folio": folio, "rama": rama, "ref": sha, "estado": "liberado"})
                continue
            if otro["estado"] not in {"Activo", "Borrador", "Completado"}:
                raise ErrorAcuerdo(f"Inventario nativo sin estado de claim atribuible: {rama}.")
            conflicto = next(((propia, ajena) for propia in cambios_propios for ajena in otro["alcance"]
                              if _zonas_solapadas(propia, ajena)), None)
            if conflicto:
                raise ErrorAcuerdo(f"Claim de {folio} en {rama}: {conflicto[1]} se solapa con {conflicto[0]}.")
            contrato = _solape_contratos(repo, plan, cambios_propios, captura, otro)
            if contrato:
                raise ErrorAcuerdo(f"Claim de {folio} en {rama}: escritura y dependencia vigente de {contrato}.")
            inventario.append({"folio": folio, "rama": rama, "ref": sha, "estado": "vigente"})
    if referencias != _git_refs_nativas(repo) or worktrees != _git_worktrees_nativos(repo):
        raise ErrorAcuerdo("El inventario Git cambió durante el preflight.")
    return inventario


def _fecha_recibo(valor):
    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        if fecha.tzinfo is None:
            raise ValueError("falta zona horaria")
        return fecha
    except (AttributeError, ValueError) as exc:
        raise ErrorAcuerdo(f"Fecha de recibo o permiso inválida: {valor!r}.") from exc


def _cotejar_recibo(esperado, registro, hoja):
    if (not isinstance(registro, dict)
            or any(registro.get(clave) != valor or type(registro.get(clave)) is not type(valor)
                   for clave, valor in esperado.items())
            or not isinstance(registro.get("approval"), str) or not registro["approval"].strip()):
        raise ErrorAcuerdo(f"Registro de ficha alterado o ajeno a la fase y al actor: {hoja}.")


def _estado_ficha(bytes_ficha, inicial, final):
    """Reemplaza sólo el valor del estado en el JSON frontal."""
    texto = bytes_ficha.decode("utf-8")
    bloque = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", texto, re.S)
    if not bloque:
        raise ErrorAcuerdo("No se encuentra la cabecera JSON de la ficha.")
    raw = bloque[1]
    decoder = json.JSONDecoder()
    pos = len(raw) - len(raw.lstrip())
    if raw[pos:pos + 1] != "{":
        raise ErrorAcuerdo("La cabecera de ficha requiere un objeto.")
    pos += 1
    while pos < len(raw):
        pos += len(raw[pos:]) - len(raw[pos:].lstrip())
        clave, pos = decoder.raw_decode(raw, pos)
        inicio = raw.index(":", pos) + 1
        inicio += len(raw[inicio:]) - len(raw[inicio:].lstrip())
        valor, fin = decoder.raw_decode(raw, inicio)
        if clave == "estado" and valor == inicial:
            desplazamiento = bloque.start(1)
            return (texto[:desplazamiento + inicio] + json.dumps(final)
                    + texto[desplazamiento + fin:]).encode("utf-8")
        pos = fin + len(raw[fin:]) - len(raw[fin:].lstrip())
        if raw[pos:pos + 1] != ",":
            break
        pos += 1
    raise ErrorAcuerdo(f"Falta la transición de estado {inicial} a {final}.")


def _aprobaciones_recibo(repo, handoff, origen, esperado, plan):
    aprobaciones = handoff.get("approvals")
    manifest = handoff.get("manifest")
    evidencia = handoff.get("evidence_sha256", {})
    if (not isinstance(aprobaciones, dict) or set(aprobaciones) != {"handoff", "feature", "plan"}
            or not isinstance(manifest, dict) or not isinstance(evidencia, dict)):
        raise ErrorAcuerdo("Recibo de relevo sin expediente documental completo.")
    for tipo, ancla in aprobaciones.items():
        ruta = ancla.get("path") if isinstance(ancla, dict) else None
        if (not isinstance(ruta, str) or
                not (ruta == plan["ruta"] or ruta in manifest or ruta in evidencia)):
            raise ErrorAcuerdo(f"Fuente ajena a la aprobación de {tipo} del relevo.")
        fuente = repo.fuente(ruta)
        texto = repo.texto(ruta)
        cita = ancla.get("quote")
        if (not isinstance(cita, str) or not cita.strip() or f"«{cita}»" not in texto
                or (ruta in evidencia and fuente.sha256 != evidencia[ruta])):
            raise ErrorAcuerdo(f"No se encuentra la cita y huella originales de {tipo}: {ruta}.")
        if tipo == "feature" and ancla.get("approved_sha256") != esperado["before_sha256"]:
            raise ErrorAcuerdo("La aprobación de ficha no identifica sus bytes de origen.")
        if tipo == "plan":
            sha = _identidad_nativa(ancla.get("approved_sha256"), r"[0-9a-f]{64}", "huella de plan aprobado")
            if sha != handoff.get("s_plan_sha256") and sha not in texto:
                raise ErrorAcuerdo("La aprobación original del plan no coteja su huella.")
        if tipo == "handoff" and any(not re.search(
                rf"(?<![A-Za-z0-9_.-]){re.escape(actor)}(?![A-Za-z0-9_.-])", texto)
                for actor in (origen, esperado["session_id"])):
            raise ErrorAcuerdo("El documento de relevo no identifica origen y receptor.")


def _cotejar_handoff_ficha(repo, autoridad, registro, esperado, antes, fase, hoja):
    handoff = registro["handoff"]
    relevo = autoridad.get("relevo")
    plan, tx = autoridad["plan"], autoridad["transaccion"]
    actor = autoridad["actor"]
    rama_handoff = f"codex/PLANIFICACION/{tx}"
    if not isinstance(handoff, dict) or not isinstance(relevo, dict):
        raise ErrorAcuerdo(f"El recibo de relevo requiere la autoridad del receptor: {hoja}.")
    origen = relevo["actor_saliente"]
    esperado_handoff = {
        **{k: esperado[k] for k in ("schema_version", "session_id", "project_id", "profile_version",
                                     "profile_hash", "root", "target", "identity", "revision",
                                     "before_sha256", "after_sha256")},
        "operation": "feature-handoff", "origin_session_id": origen, "issuer": actor,
        "transaction_id": tx, "branch": rama_handoff, "common_dir": str(repo.comun),
        "s_plan": plan["ruta"], "s_version": plan["version"], "module": plan["modulo"],
    }
    if (registro.get("branch") != rama_handoff or registro.get("transaction_id") != tx
            or any(handoff.get(k) != v for k, v in esperado_handoff.items())):
        raise ErrorAcuerdo(f"El relevo del recibo no corresponde a raíz, plan o transacción: {hoja}.")
    identidades = {origen, actor, tx}
    previo = relevo.get("anterior")
    while isinstance(previo, dict):
        identidades.add(previo["actor_saliente"])
        previo = previo.get("anterior")
    historicos = handoff.get("historical_session_ids", sorted({origen, actor, tx}))
    if not isinstance(historicos, list) or any(not isinstance(x, str) for x in historicos) or sorted(identidades) != sorted(historicos):
        raise ErrorAcuerdo(f"Actores históricos de relevo inconsistentes: {hoja}.")
    try:
        contenido = base64.b64decode(handoff["before_content"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorAcuerdo(f"El recibo no conserva el Borrador original: {hoja}.") from exc
    if contenido != antes:
        raise ErrorAcuerdo(f"El recibo de relevo altera el Borrador original: {hoja}.")
    head = _identidad_nativa(handoff.get("head"), OID, "HEAD preparado")
    base = _identidad_nativa(handoff.get("main"), OID, "main preparado")
    planif = repo.commit_ref("refs/heads/" + rama_handoff)
    if (not _ancestro_nativo(repo, base, head) or not _ancestro_nativo(repo, head, planif)
            or not _ancestro_nativo(repo, planif, autoridad["ref_activo"])):
        raise ErrorAcuerdo(f"Las refs del relevo de ficha no preceden a la activación: {hoja}.")
    texto_plan = repo.texto(plan["ruta"])
    base_plan = re.sub(r"^(\*\*Estado:\*\*) (?:Borrador|Activo)$", r"\1 Borrador", texto_plan, flags=re.M)
    firma_plan = huella_bytes(base_plan.encode())
    if handoff.get("s_plan_fingerprint") != firma_plan:
        raise ErrorAcuerdo(f"El recibo liga otro texto de plan: {hoja}.")
    _aprobaciones_recibo(repo, handoff, origen, esperado, plan)
    aprobada = _fecha_recibo(handoff.get("approved_at"))
    vence = _fecha_recibo(handoff.get("expires_at"))
    if not (timedelta(0) < vence - aprobada <= timedelta(minutes=15)):
        raise ErrorAcuerdo(f"Vigencia original del relevo inválida: {hoja}.")
    ahora = datetime.now(timezone.utc)
    if fase == "alta" and not aprobada <= ahora < vence:
        raise ErrorAcuerdo(f"Permiso de relevo pendiente vencido: {hoja}.")
    if fase != "alta":
        validada = _fecha_recibo(registro.get("validated_at"))
        if not aprobada <= validada <= ahora + timedelta(minutes=1):
            raise ErrorAcuerdo(f"Recibo de relevo sin validación durable: {hoja}.")
        if repo.runtime(f".{repo.proyecto}/runtime/feature-handoffs/{tx}/{esperado['identity']}.json") is not None:
            raise ErrorAcuerdo(f"El relevo todavía tiene un permiso pendiente: {hoja}.")


def _ficha_nativa_preflight(repo, autoridad, ruta, fase):
    actor, tx = autoridad["actor"], autoridad["transaccion"]
    ficha = re.fullmatch(rf"sdd/funcionalidades/({FICHA})(?:_[^/]+)?\.md", ruta)
    if ficha is None:
        return None
    entrada = repo.lector.entrada(ruta)
    if entrada is None:
        return None
    actual = entrada[1]
    datos, _ = frontal(actual.decode("utf-8"), ruta)
    if datos.get("id") != ficha[1]:
        raise ErrorAcuerdo(f"Identidad de ficha ajena a {ruta}.")
    estado = datos.get("estado")
    if estado != "Validado" and not (fase == "alta" and estado == "Borrador"):
        return None

    cabeza = repo.en_arbol(repo.commit or repo.head, historico=True)
    registrado = cabeza.lector.entrada(ruta)
    if fase == "historica":
        if registrado is None or registrado[1] != actual:
            raise ErrorAcuerdo(f"La consulta histórica requiere ficha guardada: {ruta}.")
        return {"ficha": ruta, "estado": "historico", "ref": cabeza.commit}

    base = repo.en_arbol(autoridad["base"], historico=True)
    activa = repo.en_arbol(autoridad["ref_activo"], historico=True)
    antepasados = [r[1] for fuente in (cabeza, activa, base) if (r := fuente.lector.entrada(ruta))]
    if antepasados and frontal(antepasados[-1].decode("utf-8"), ruta)[0].get("estado") == "Validado":
        if fase == "alta":
            raise ErrorAcuerdo(f"La ficha ya existía validada: {ruta}.")
        return None
    if fase != "alta" and registrado and registrado[1] == actual:
        return {"ficha": ruta, "estado": "historico", "ref": cabeza.commit}
    anterior = next((imagen for imagen in antepasados
                     if frontal(imagen.decode("utf-8"), ruta)[0].get("estado") == "Borrador"), None)
    if estado == "Borrador":
        anterior, nuevo = actual, _estado_ficha(actual, "Borrador", "Validado")
    else:
        nuevo = actual
        if anterior is None:
            anterior = _estado_ficha(nuevo, "Validado", "Borrador")
        if _estado_ficha(anterior, "Borrador", "Validado") != nuevo:
            raise ErrorAcuerdo(f"El alta cambió bytes fuera del estado de la ficha: {ruta}.")

    nombre = f".{repo.proyecto}/runtime/feature-validations/{tx}/{ficha[1]}"
    recibo, permiso, diario = (repo.runtime(nombre + extension)
                               for extension in (".receipt.json", ".json", ".transaction.json"))
    if diario is not None:
        raise ErrorAcuerdo(f"Diario parcial de validación: {nombre}.transaction.json.")
    if fase == "alta":
        if recibo is not None:
            raise ErrorAcuerdo(f"Permiso de un uso ya consumido: {nombre}.")
        registro, extension = permiso, ".json"
    else:
        if permiso is not None or recibo is None or recibo.get("receipt") != "validated":
            raise ErrorAcuerdo(f"El alta requiere el recibo nativo consumido y sin permiso pendiente: {nombre}.")
        registro, extension = recibo, ".receipt.json"
    es_relevo = isinstance(registro, dict) and registro.get("handoff") is not None
    esperado = {
        "schema_version": 1, "operation": "validate-feature", "session_id": actor,
        "project_id": repo.proyecto, "profile_version": 2, "profile_hash": repo.perfil_hash,
        "root": str(repo.raiz), "branch": f"codex/PLANIFICACION/{tx}" if es_relevo else repo.rama,
        "target": str(repo.raiz / ruta), "identity": ficha[1], "revision": 1,
        "before_sha256": huella_bytes(anterior), "after_sha256": huella_bytes(nuevo),
    }
    _cotejar_recibo(esperado, registro, nombre)
    if es_relevo:
        _cotejar_handoff_ficha(repo, autoridad, registro, esperado, anterior, fase, nombre)
    if fase == "alta":
        aprobada = _fecha_recibo(permiso.get("approved_at"))
        vence = _fecha_recibo(permiso.get("expires_at"))
        ahora = datetime.now(timezone.utc)
        if not (timedelta(0) < vence - aprobada <= timedelta(minutes=15)
                and aprobada <= ahora + timedelta(minutes=1) and ahora < vence):
            raise ErrorAcuerdo(f"Permiso pendiente vencido: {nombre}.")
    else:
        _fecha_recibo(recibo.get("validated_at"))
    return {"ficha": ruta, "estado": "pendiente" if fase == "alta" else "consumido",
            "fuente": nombre + extension}

def _excepciones_nativas(repo, autoridad, entrada, rutas):
    excepciones = entrada.get("excepciones", [])
    if not isinstance(excepciones, list):
        raise ErrorAcuerdo("Las excepciones deben ser una lista de fuentes aplicables.")
    base = repo.en_arbol(autoridad["base"], historico=True)
    salida = []
    for dato in excepciones:
        if not isinstance(dato, dict) or not isinstance(dato.get("ruta"), str) or dato["ruta"] not in rutas:
            raise ErrorAcuerdo("Excepción ajena al lote nativo.")
        ruta = dato["ruta"]
        fuente = dato.get("fuente")
        revisor = _identidad_nativa(dato.get("revisor"), ACTOR, "revisor")
        if (revisor in (autoridad["actor"], autoridad["transaccion"]) or not isinstance(fuente, str)
                or not fuente.startswith(autoridad["plan"]["estado_modulo"].removesuffix("estado.md") + "anexos/")):
            raise ErrorAcuerdo(f"Dictamen de excepción sin revisión independiente: {ruta}.")
        origen = repo.en_arbol(repo.commit or repo.head, historico=True)
        texto = objeto(origen.leer(fuente), fuente)
        previo, nuevo = base.lector.entrada(ruta), repo.lector.entrada(ruta)
        vinculo = dato.get("obligacion")
        if (not isinstance(vinculo, str) or not vinculo.strip()
                or texto.get("estado") != "aprobado" or texto.get("ruta") != ruta
                or texto.get("revisor") != revisor or texto.get("obligacion") != vinculo
                or texto.get("antes") != (huella_bytes(previo[1]) if previo else None)
                or texto.get("despues") != (huella_bytes(nuevo[1]) if nuevo else None)):
            raise ErrorAcuerdo(f"Dictamen ajeno o incompatible con el contenido y obligación: {ruta}.")
        if repo.fuente(fuente).sha256 != origen.fuente(fuente).sha256:
            raise ErrorAcuerdo(f"El dictamen presenta cambios sin guardar: {fuente}.")
        salida.append(dict(dato, sha256=origen.fuente(fuente).sha256))
    return salida


def preflight_nativo(repo, folio, entrada, *, rutas=(), fase="trabajo"):
    """Coteja un lote y su inventario sin emitir, consumir ni guardar permisos."""
    if not isinstance(entrada, dict):
        raise ErrorAcuerdo("Se requiere una entrada documental de preflight.")
    if fase == "historica":
        autoridad = procedencia_acuerdo_nativo(repo, folio, ref_acuerdo=entrada.get("ref_acuerdo"),
                                             base=entrada.get("base"), transaccion=entrada.get("transaccion"))
        autoridad.update(actor=entrada.get("actor"), autoridad_cotejada=False, limites={"autoridad": False})
    else:
        autoridad = comprobar_autoridad_nativa(repo, folio, entrada, fase=fase)
    try:
        if not isinstance(fase, str) or not fase:
            raise ErrorAcuerdo("El preflight requiere una fase documental.")
        plan = autoridad["plan"]
        rutas = _rutas_preflight(repo, plan, rutas)
        fuente = f"codex/{folio}/{autoridad['transaccion']}" if fase == "integracion" else None
        claims = [] if fase == "historica" else _claims_nativos(
            repo, plan, autoridad["transaccion"], rutas, rama_fuente=fuente,
        )
        recibos = [_ficha_nativa_preflight(repo, autoridad, ruta, fase) for ruta in rutas]
        excepciones = _excepciones_nativas(repo, autoridad, entrada, rutas)
        return dict(autoridad, claims=claims, recibos=[r for r in recibos if r is not None],
                    excepciones=excepciones)
    except (ErrorConvivencia, ErrorArbol, OSError, UnicodeError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc


def _rutas_preflight(repo, plan, rutas):
    if isinstance(rutas, str):
        raise ErrorAcuerdo("El preflight requiere un conjunto de rutas literales.")
    destinos = sorted(set(ruta_git(ruta) for ruta in rutas))
    for ruta in destinos:
        repo.lector.comprobar_ruta(ruta)
        if repo.arbol == "staged":
            comprobar_ruta_trabajo(repo.raiz, ruta)
        if (not _en_ruta_dominio(ruta, plan["dominio"], repo.raices_solucion)
                or not any(cubre_ruta(patron, ruta) for patron in plan["alcance"])):
            raise ErrorAcuerdo(f"Fuera del alcance nativo de {plan['folio']}: {ruta}.")
    return destinos


def preflight_activacion_nativo(repo, folio, entrada, *, propuesta, rutas=()):
    """Valida activación sobre un Borrador guardado y un plan propuesto cotejado por el llamante."""
    try:
        if not isinstance(repo, RepositorioNativo) or not isinstance(entrada, dict) or not isinstance(propuesta, dict):
            raise ErrorAcuerdo("Se requieren repositorio, pedido y plan propuesto de activación.")
        actor = _identidad_nativa(entrada.get("actor"), ACTOR, "actor")
        tx = _identidad_nativa(entrada.get("transaccion"), ACTOR, "transacción")
        ref = _identidad_nativa(entrada.get("ref_acuerdo"), OID, "ref de Borrador")
        base = _identidad_nativa(entrada.get("base"), OID, "base aprobada")
        ramas = (f"codex/PLANIFICACION/{tx}", f"codex/{folio}/{tx}")
        fase_observada = repo.rama == ramas[1] and repo.commit is not None and repo.commit == repo.head
        if actor != tx or repo.rama not in ramas:
            raise ErrorAcuerdo("La activación requiere el checkout del escritor de planificación o ejecución.")
        if repo.head != ref:
            if (not fase_observada or repo.git("rev-list", "--parents", "-n", "1", repo.commit)
                    .decode("ascii").split()[1:] != [ref]
                    or _campos_acuerdo_nativo(repo.plan(folio)) != _campos_acuerdo_nativo(propuesta)
                    or repo.plan(folio)["blob"] != propuesta.get("blob")):
                raise ErrorAcuerdo("El guardado de activación no corresponde al Borrador y propuesta exactos.")
        if not _ancestro_nativo(repo, base, ref):
            raise ErrorAcuerdo("La base aprobada no precede al Borrador guardado.")
        borrador = repo.en_arbol(ref, historico=True).plan(folio)
        if (borrador["estado"] != "Borrador" or propuesta.get("estado") != "Activo"
                or any(propuesta.get(c) != valor for c, valor in _identidad_plan_nativo(borrador).items())
                or borrador.get("base") not in (None, base)
                or borrador.get("transaccion") not in (None, tx)
                or propuesta.get("transaccion") not in (None, tx)
                or not isinstance(entrada.get("cita"), str) or not entrada["cita"].strip()
                or not isinstance(propuesta.get("cita"), str) or propuesta["cita"] != entrada["cita"]
                or propuesta.get("base") != base or propuesta["version"] != entrada.get("version")):
            raise ErrorAcuerdo("La activación cambió alcance, fuente, versión, base o cita del Borrador.")
        activos = repo.comprobar_activos(repo.rutas_planes())
        if borrador["dominio"] in activos and activos[borrador["dominio"]] != borrador["ruta"]:
            raise ErrorAcuerdo("Ya existe otro plan Activo en el dominio del Borrador.")
        destinos = _rutas_preflight(repo, propuesta, rutas)
        claims = _claims_nativos(repo, propuesta, tx, destinos)
        fuente = {**_campos_acuerdo_nativo(propuesta), "blob_borrador": borrador["blob"]}
        return {
            "schema": 1, "actor": actor, "transaccion": tx, "base": base, "ref_acuerdo": ref,
            "plan": propuesta, "huella_acuerdo": _hash(fuente), "autoridad_cotejada": True,
            "claims": claims, "recibos": [], "excepciones": [],
            "limites": {"autoridad": False},
        }
    except (ErrorConvivencia, ErrorArbol, OSError, UnicodeError) as exc:
        raise ErrorAcuerdo(str(exc)) from exc
