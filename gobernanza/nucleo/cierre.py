"""Cierre preparado y confirmación de merge exacto; F-0107@r1.

No ejecuta pruebas ni integra ramas. Los resultados humanos son registros
cooperativos versionados de una comunicación real, no firmas ni inferencias del
agente. La caché de confirmación es descartable y nunca se usa como autoridad.
"""

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from .acuerdos import _commit, _frontmatter, normalizar_autoridad, validar_cambios
from .arboles import LectorArbol, _git, _leer_trabajo, _raiz_repositorio, materializar
from .convivencia import (ACTOR, OID, PERFIL, RAMA, ErrorConvivencia, huella_bytes, huella_datos,
                          seleccionar_perfil)
from .documentos import json_estricto
from .modelo import coincide, diagnostico, resultado
from .validacion import validar
from .verificacion import _entradas, _hash, evidencia_vigente
from .versiones import MANIFIESTO, historial, preparar_version


def _salida(operacion, errores=()):
    salida = resultado(operacion, errores)
    salida.update(entrega_lista=False, cierre=None, commit_cierre=None, integracion_confirmada=False)
    salida["resumen"] = "Control de cierre sin ejecutar pruebas ni actualizar el destino de integración."
    return salida


def _fallo(operacion, mensaje, ruta="cierre", codigo="CIERRE_INVALIDO"):
    return _salida(operacion, [diagnostico(codigo, ruta, "Cierre ligado al acuerdo, evidencia y refs reales",
                                         mensaje, "Corrige la causa, concilia las refs y vuelve a preparar o confirmar.")])


def _id(sesion):
    if not isinstance(sesion, str) or not re.fullmatch(r"[SG]\d{2}-\d{2}", sesion):
        raise ValueError("Se requiere una identidad de sesión SNN-NN o GNN-NN.")
    return sesion


def _registro(sesion):
    return f"sesiones/estado/{_id(sesion)}/cierre.json"


def _destino(raiz, destino):
    if not isinstance(destino, str) or not destino:
        raise ValueError("Se requiere una rama local de destino.")
    ref = destino if destino.startswith("refs/heads/") else "refs/heads/" + destino
    if destino.startswith("refs/") and not destino.startswith("refs/heads/"):
        raise ValueError("El destino debe ser una rama local bajo refs/heads/.")
    _git(raiz, "check-ref-format", ref)
    return ref


def _lista_ids(valores, nombre):
    if (not isinstance(valores, list) or any(not isinstance(v, str) or not v.strip() for v in valores)
            or len(valores) != len(set(valores))):
        raise ValueError(f"{nombre} debe ser una lista de identidades únicas no vacías.")
    return set(valores)


def _destino_deuda(destino):
    if not isinstance(destino, str) or not destino.strip() or "\\" in destino:
        return False
    if re.fullmatch(r"[SG]\d{2}-\d{2}", destino):
        return True
    if PurePosixPath(destino).is_absolute() or ".." in PurePosixPath(destino).parts:
        return False
    return bool(re.fullmatch(r"(?:backlog/|backlog:|sdd/backlog\.md#)[A-Za-z0-9][A-Za-z0-9_./#-]*", destino))


def _obligaciones_humanas(datos, acuerdo, informe, criterios):
    promesa = acuerdo["datos"]["acuerdo"]
    casos = promesa.get("casos_humanos", [])
    if not isinstance(casos, list):
        raise ValueError("casos_humanos debe ser una lista explícita.")
    requeridos = {}
    for caso in casos:
        if (not isinstance(caso, dict) or not isinstance(caso.get("id"), str) or not caso["id"].strip()
                or caso["id"] in requeridos or caso.get("criterio") not in criterios):
            raise ValueError("Caso humano duplicado, inválido o sin criterio resoluble.")
        requeridos[caso["id"]] = caso["criterio"]
    registros = datos.get("resultados_humanos", [])
    if not isinstance(registros, list):
        raise ValueError("resultados_humanos debe ser una lista de registros versionados.")
    por_id = {}
    for registro in registros:
        if not isinstance(registro, dict) or not isinstance(registro.get("id"), str) or not registro["id"] or registro["id"] in por_id:
            raise ValueError("Los resultados humanos deben identificar casos sin duplicados.")
        por_id[registro["id"]] = registro
    for identidad in requeridos:
        registro = por_id.get(identidad)
        if (registro is None or registro.get("resultado") != "pasa"
                or registro.get("version") != informe["huella_entradas"]
                or not isinstance(registro.get("referencia_comunicacion"), str)
                or not registro["referencia_comunicacion"].strip()):
            raise ValueError(f"El caso humano {identidad} requiere resultado real comunicado para la versión revisada.")
    enmiendas = _lista_ids(promesa.get("enmiendas_requeridas", []), "enmiendas_requeridas")
    incorporadas = _lista_ids(datos.get("enmiendas_incorporadas", []), "enmiendas_incorporadas")
    if not enmiendas.issubset(incorporadas):
        raise ValueError("Quedan enmiendas requeridas sin incorporar.")
    deuda = _lista_ids(promesa.get("deuda_requerida", []), "deuda_requerida")
    asignaciones = datos.get("deuda_asignada", [])
    if not isinstance(asignaciones, list):
        raise ValueError("deuda_asignada debe identificar deuda y destino concreto.")
    asignadas = set()
    for asignacion in asignaciones:
        if (not isinstance(asignacion, dict) or not isinstance(asignacion.get("id"), str)
                or not asignacion["id"].strip() or asignacion["id"] in asignadas
                or not _destino_deuda(asignacion.get("destino"))):
            raise ValueError("La deuda requiere ID único y referencia concreta a sesión o backlog.")
        asignadas.add(asignacion["id"])
    if not deuda.issubset(asignadas):
        raise ValueError("Queda deuda requerida sin destino asignado.")
    for campo in ("enmiendas_pendientes", "deuda_sin_asignar"):
        if _lista_ids(datos.get(campo, []), campo):
            raise ValueError(f"No puede cerrarse con {campo}.")
    return sorted(requeridos)


def evaluar_entrega(raiz, sesion, informe, *, arbol="HEAD", acuerdo=None, preparacion=None, dictamenes=(),
                    entrada_nativa=None):
    """Evalúa documentos y evidencia existente, sin ejecutar runners ni escribir."""
    try:
        nativo = seleccionar_perfil(raiz, arbol, requiere_nativo=entrada_nativa is not None)
        if nativo is not None:
            return _evaluar_nativo(nativo, sesion, informe, entrada_nativa)
        _id(sesion)
        raiz = _raiz_repositorio(raiz)
        selector = arbol if arbol in {"worktree", "staged"} else _commit(raiz, arbol)
        if (not isinstance(informe, dict) or type(informe.get("schema")) is not int or informe["schema"] != 1
                or informe.get("etapa") != "entrega" or type(informe.get("codigo")) is not int
                or informe["codigo"] != 0 or informe.get("pruebas_aprobadas") is not True
                or informe.get("sesion") != sesion):
            raise ValueError("Se requiere un informe real satisfactorio de entrega para esta sesión.")
        acuerdo = informe.get("acuerdo") if acuerdo is None else acuerdo
        if not isinstance(acuerdo, dict) or acuerdo != informe.get("acuerdo"):
            raise ValueError("El acuerdo de evaluación debe coincidir con la captura ligada al informe.")
        vigente = evidencia_vigente(raiz, informe, arbol=selector)
        if vigente["codigo"] or vigente.get("vigente") is not True:
            return _salida("evaluar_entrega", vigente["errores"])
        if preparacion is not None:
            if (not isinstance(preparacion, dict) or preparacion.get("etapa") != "preparacion"
                    or preparacion.get("preparacion_satisfecha") is not True):
                raise ValueError("La preparación proporcionada no es un informe satisfactorio de preparación.")
            anterior = evidencia_vigente(raiz, preparacion, arbol=selector)
            if anterior["codigo"]:
                return _salida("evaluar_entrega", anterior["errores"])
        control = validar_cambios(raiz, sesion, acuerdo, arbol=selector, fase="entrega", preparacion=preparacion, dictamenes=dictamenes)
        if control["codigo"]:
            return _salida("evaluar_entrega", control["errores"])
        with materializar(raiz, selector) as copia:
            estructura = validar(copia.raiz)
            if estructura["codigo"]:
                return _salida("evaluar_entrega", estructura["errores"])
            autoridad = normalizar_autoridad(copia.raiz, sesion)
            if autoridad["huella_acuerdo"] != acuerdo["huella_acuerdo"]:
                raise ValueError("El candidato cambió la autoridad del informe.")
            datos, _ = _frontmatter(copia.raiz / autoridad["ruta_sesion"])
            criterios = {c["referencia"] for c in estructura["criterios"]}
            humanos = _obligaciones_humanas(datos, acuerdo, informe, criterios)
            huella_arbol = copia.huella
        with materializar(raiz, selector) as actual:
            if actual.huella != huella_arbol:
                raise ValueError("El árbol cambió durante la evaluación; repite sobre una ref estable.")
        salida = _salida("evaluar_entrega")
        salida.update(entrega_lista=True, acuerdo=acuerdo, huella_entradas=informe["huella_entradas"],
                      huella_informe=informe["huella_informe"], casos_humanos_registrados=humanos,
                      arbol=selector, huella_arbol=huella_arbol)
        return salida
    except ErrorConvivencia as exc:
        return _fallo("evaluar_entrega", exc.mensaje, exc.ruta, exc.codigo)
    except Exception as exc:
        return _fallo("evaluar_entrega", str(exc) or type(exc).__name__)


def _json(datos):
    return (json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _recibo(datos, sesion):
    if not isinstance(datos, dict) or type(datos.get("schema")) is not int or datos["schema"] != 1 or datos.get("sesion") != sesion:
        raise ValueError("Manifiesto de cierre ausente o inválido para esta sesión.")
    sin_huella = {k: v for k, v in datos.items() if k != "huella_cierre"}
    if datos.get("huella_cierre") != _hash(sin_huella):
        raise ValueError("El manifiesto de cierre fue alterado o está incompleto.")
    return datos


def _leer_recibo(raiz, commit, sesion, *, permitir_ausente=False):
    with materializar(raiz, commit) as copia:
        relativa = _registro(sesion)
        ruta = copia.raiz / relativa
        if permitir_ausente and relativa not in copia.archivos and not ruta.exists() and not ruta.is_symlink():
            return None
        if not ruta.is_file() or ruta.is_symlink():
            raise ValueError("No existe un manifiesto de cierre regular en la punta preparada.")
        return _recibo(json_estricto(ruta.read_text(encoding="utf-8")), sesion)


def _padres(raiz, commit):
    return _git(raiz, "rev-list", "--parents", "-n", "1", commit).decode("ascii").split()[1:]


def _creador(raiz, commit, sesion):
    return _git(raiz, "log", "-1", "--format=%H", commit, "--", _registro(sesion)).strip().decode("ascii")


def _estado_lista(texto, registro, huella):
    lineas = texto.splitlines(keepends=True)
    fin = next(i for i in range(1, len(lineas)) if lineas[i].strip() == "---")
    datos = json_estricto("".join(lineas[1:fin]))
    datos["estado"] = "lista"
    datos["cierre_preparado"] = {"manifiesto": registro, "huella_entradas": huella}
    return ("---\n" + json.dumps(datos, ensure_ascii=False) + "\n---\n" + "".join(lineas[fin + 1:])).encode("utf-8")


def _cotejar_version(raiz, recibo, observado):
    fuente = recibo["fuente_entrada"]
    esperada = None
    if recibo["destino"] == "refs/heads/main":
        esperada = preparar_version(
            raiz, recibo["base_integracion"], fuente, recibo["acuerdo"], recibo["informe"])
    if recibo.get("version_aplicacion") != esperada:
        raise ValueError("El recibo de cierre no liga la versión de aplicación del candidato.")
    if esperada is not None:
        contenido = LectorArbol(raiz, observado).leer(MANIFIESTO)
        if json_estricto(contenido.decode("utf-8")) != esperada:
            raise ValueError(f"El registro integrado no coincide con {MANIFIESTO}.")
    elif _git(raiz, "diff", "--no-ext-diff", "--name-only", fuente, observado, "--", MANIFIESTO):
        raise ValueError(f"El cierre alteró {MANIFIESTO} sin una versión aplicable.")
    return esperada


def preparar_cierre(raiz, sesion, informe, *, destino="main", acuerdo=None, preparacion=None, dictamenes=(),
                    entrada_nativa=None):
    """Guarda un candidato documental, verificando destino sin integrarlo."""
    try:
        from .inicio import guardar_documentos
        nativo = seleccionar_perfil(raiz, "HEAD", requiere_nativo=entrada_nativa is not None)
        if nativo is not None:
            _destino_nativo(destino)
            return _preparar_nativo(nativo, sesion, informe, entrada_nativa)
        _id(sesion)
        raiz = _raiz_repositorio(raiz)
        fuente = _commit(raiz, "HEAD")
        rama = _git(raiz, "symbolic-ref", "--quiet", "HEAD").strip().decode("utf-8")
        ref_destino = _destino(raiz, destino)
        if rama == ref_destino:
            raise ValueError("La rama fuente debe ser distinta del destino; no se prepara un cierre sobre main.")
        base = _commit(raiz, ref_destino)
        try:
            _git(raiz, "merge-base", "--is-ancestor", base, fuente)
        except ValueError as exc:
            raise ValueError("El destino divergió de la fuente: concilia las ramas antes de preparar; no se hace merge automático.") from exc
        evaluacion = evaluar_entrega(raiz, sesion, informe, arbol=fuente, acuerdo=acuerdo, preparacion=preparacion, dictamenes=dictamenes)
        if evaluacion["codigo"]:
            return _salida("preparar_cierre", evaluacion["errores"])
        acuerdo = evaluacion["acuerdo"]
        registro = _registro(sesion)
        anterior = _leer_recibo(raiz, fuente, sesion, permitir_ausente=True)
        if (anterior is not None and _creador(raiz, fuente, sesion) == fuente
                and _padres(raiz, fuente) == [anterior.get("fuente_entrada")]
                and anterior.get("destino") == ref_destino and anterior.get("base_integracion") == base
                and anterior.get("informe") == informe and anterior.get("acuerdo") == acuerdo):
            version = _cotejar_version(raiz, anterior, fuente)
            if _commit(raiz, "HEAD") != fuente or _commit(raiz, ref_destino) != base:
                raise ValueError("Fuente o destino cambiaron durante el cotejo del cierre preparado.")
            salida = _salida("preparar_cierre")
            salida.update(entrega_lista=True, cierre=anterior, commit_cierre=fuente, idempotente=True)
            if version is not None:
                salida["version_aplicacion"] = version
            return salida
        manifiesto = dict(schema=1, sesion=sesion, destino=ref_destino, base_integracion=base,
                          fuente_entrada=fuente, huella_entradas=informe["huella_entradas"],
                          huella_informe=informe["huella_informe"], huella_acuerdo=acuerdo["huella_acuerdo"],
                          informe=copy.deepcopy(informe), acuerdo=copy.deepcopy(acuerdo),
                          preparacion=copy.deepcopy(preparacion), dictamenes=copy.deepcopy(list(dictamenes)))
        version = (preparar_version(raiz, base, fuente, acuerdo, informe)
                   if ref_destino == "refs/heads/main" else None)
        if version is not None:
            manifiesto["version_aplicacion"] = version
        manifiesto["huella_cierre"] = _hash(manifiesto)
        with materializar(raiz, fuente) as copia:
            ruta_sesion = acuerdo["ruta_sesion"]
            documentos = {registro: _json(manifiesto)}
            if ruta_sesion.startswith("sdd/registro/"):
                datos, _ = _frontmatter(copia.raiz / ruta_sesion)
                if datos["estado"] != "lista":
                    raise ValueError("El cierre requiere la transición SDD registrada al estado lista.")
            else:
                documentos[ruta_sesion] = _estado_lista((copia.raiz / ruta_sesion).read_text(encoding="utf-8"),
                                                       registro, informe["huella_entradas"])
            if version is not None:
                documentos[MANIFIESTO] = _json(version)
            alcance = acuerdo["datos"]["acuerdo"]["alcance"]["documentos"]
            fuera = [ruta for ruta in documentos if not any(coincide(ruta, p) for p in alcance)]
            if fuera:
                raise ValueError("Registros de cierre fuera del alcance documental autorizado: " + ", ".join(fuera))
            archivos = copy.deepcopy(copia.archivos)
            for relativa, contenido in documentos.items():
                ruta = copia.raiz / relativa
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(contenido)
                archivos[relativa] = {"sha256": hashlib.sha256(contenido).hexdigest(), "modo": "100644"}
            candidato = replace(copia, archivos=archivos)
            estructura = validar(copia.raiz)
            if estructura["codigo"]:
                return _salida("preparar_cierre", estructura["errores"])
            _, entradas, autoridad = _entradas(candidato, sesion)
            if _hash(entradas) != informe["huella_entradas"] or autoridad["huella_acuerdo"] != acuerdo["huella_acuerdo"]:
                raise ValueError("El cierre documental cambia entradas verificadas; revisa configuración y salidas.")
        if _commit(raiz, "HEAD") != fuente or _commit(raiz, ref_destino) != base:
            raise ValueError("Fuente o destino cambiaron antes del guardado.")
        commit = guardar_documentos(raiz, documentos, f"docs: preparar cierre de {sesion}",
                                    esperado=fuente, refs_esperadas={ref_destino: base})
        salida = _salida("preparar_cierre")
        salida.update(entrega_lista=True, cierre=manifiesto, commit_cierre=commit, idempotente=False)
        if version is not None:
            salida["version_aplicacion"] = version
        return salida
    except ErrorConvivencia as exc:
        return _fallo("preparar_cierre", exc.mensaje, exc.ruta, exc.codigo)
    except Exception as exc:
        return _fallo("preparar_cierre", str(exc) or type(exc).__name__)


def _guardar_cache(raiz, sesion, datos):
    gitdir = Path(os.fsdecode(_git(raiz, "rev-parse", "--absolute-git-dir")).strip()).resolve()
    actual = gitdir
    for parte in ("gobernanza", "cache"):
        actual = actual / parte
        if actual.is_symlink() or (actual.exists() and not actual.is_dir()):
            raise ValueError("La ruta de caché contiene un enlace o un archivo incompatible.")
        actual.mkdir(exist_ok=True)
    destino = actual / f"{sesion}.json"
    if destino.is_symlink() or (destino.exists() and not destino.is_file()):
        raise ValueError("El archivo de caché es un destino inseguro.")
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".cierre-", dir=actual, delete=False) as archivo:
            temporal = Path(archivo.name)
            archivo.write(_json(datos))
        temporal.replace(destino)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def confirmar_cierre(raiz, sesion, integracion, *, cierre=None, destino="main", cache=True, entrada_nativa=None):
    """Reconcilia Git y el recibo; nunca crea commits ni confía en la caché."""
    try:
        nativo = seleccionar_perfil(raiz, "HEAD", requiere_nativo=entrada_nativa is not None)
        if nativo is not None:
            _destino_nativo(destino)
            if cierre is not None:
                raise ValueError("El cierre nativo lee su permiso y lote mediante la entrada nativa.")
            return _confirmar_nativo(nativo, sesion, integracion, entrada_nativa)
        _id(sesion)
        if type(cache) is not bool:
            raise ValueError("cache debe ser booleano.")
        raiz = _raiz_repositorio(raiz)
        integrado = _commit(raiz, integracion)
        ref_destino = _destino(raiz, destino)
        destino_actual = _commit(raiz, ref_destino)
        padres = _padres(raiz, integrado)
        if len(padres) != 2:
            raise ValueError("La vía soportada requiere un merge --no-ff con exactamente dos padres.")
        base, preparada = padres
        manifiesto = _leer_recibo(raiz, preparada, sesion)
        if cierre is not None and cierre != manifiesto:
            raise ValueError("El cierre proporcionado no coincide con el recibo conservado en Git.")
        if manifiesto.get("destino") != ref_destino or manifiesto.get("base_integracion") != base:
            raise ValueError("Destino o primer padre no coinciden con la base de integración preparada.")
        if _creador(raiz, preparada, sesion) != preparada or _padres(raiz, preparada) != [manifiesto.get("fuente_entrada")]:
            raise ValueError("La punta fuente no es exactamente el commit que guardó este manifiesto.")
        try:
            _git(raiz, "merge-base", "--is-ancestor", base, manifiesto["fuente_entrada"])
        except ValueError as exc:
            raise ValueError("La base de integración diverge de la fuente de entrada; esa vía no está soportada.") from exc
        if _git(raiz, "rev-parse", integrado + "^{tree}") != _git(raiz, "rev-parse", preparada + "^{tree}"):
            raise ValueError("El merge incorpora resoluciones o archivos distintos del candidato preparado.")
        try:
            _git(raiz, "merge-base", "--is-ancestor", integrado, destino_actual)
        except ValueError as exc:
            raise ValueError("La integración no es alcanzable desde la rama de destino esperada.") from exc
        acuerdo = manifiesto["acuerdo"]
        if acuerdo["datos"]["acuerdo"].get("integracion_local") is not True:
            raise ValueError("El acuerdo no autoriza la aceptación de integración local.")
        informe = manifiesto["informe"]
        if (manifiesto.get("huella_entradas") != informe.get("huella_entradas")
                or manifiesto.get("huella_informe") != informe.get("huella_informe")
                or manifiesto.get("huella_acuerdo") != acuerdo.get("huella_acuerdo")):
            raise ValueError("El manifiesto no liga las mismas entradas, informe y acuerdo.")
        evaluacion = evaluar_entrega(raiz, sesion, informe, arbol=integrado, acuerdo=acuerdo,
                                    preparacion=manifiesto.get("preparacion"), dictamenes=manifiesto.get("dictamenes", ()))
        if evaluacion["codigo"]:
            return _salida("confirmar_cierre", evaluacion["errores"])
        version = _cotejar_version(raiz, manifiesto, integrado)
        if version is not None and not any(
            registro["commit"] == integrado and registro["version"] == version["version"]
            for registro in historial(raiz, destino_actual)
        ):
            raise ValueError("La entrega no figura en el historial de primer padre de main.")
        if _commit(raiz, ref_destino) != destino_actual:
            raise ValueError("El destino cambió durante la confirmación; repite la lectura.")
        salida = _salida("confirmar_cierre")
        salida.update(entrega_lista=True, integracion_confirmada=True, integracion=integrado,
                      commit_cierre=preparada, destino=ref_destino, base_integracion=base,
                      huella_entradas=informe["huella_entradas"], cierre=manifiesto)
        if version is not None:
            salida["version_aplicacion"] = version
        if cache:
            _guardar_cache(raiz, sesion, {"schema": 1, "sesion": sesion, "integracion": integrado,
                                        "commit_cierre": preparada, "destino": ref_destino,
                                        "integracion_confirmada": True, "fuente": "refs verificadas; cache descartable"})
        return salida
    except ErrorConvivencia as exc:
        return _fallo("confirmar_cierre", exc.mensaje, exc.ruta, exc.codigo)
    except Exception as exc:
        return _fallo("confirmar_cierre", str(exc) or type(exc).__name__)


def _destino_nativo(destino):
    if destino not in ("main", "refs/heads/main"):
        raise ValueError("La vía de integración nativa se coteja exclusivamente en main.")


def _oid(valor):
    if not isinstance(valor, str) or not re.fullmatch(OID, valor):
        raise ValueError("Se requiere un SHA literal completo de Git.")
    return valor


def _arbol_commit(repo, commit):
    return repo.git("rev-parse", "--verify", _oid(commit) + "^{tree}").decode().strip()


def _padres_commit(repo, commit):
    datos = repo.git("rev-list", "--parents", "-n", "1", _oid(commit)).decode("ascii").split()
    if not datos or datos[0] != commit:
        raise ValueError("No se pudo cotejar la identidad del commit solicitado.")
    return datos[1:]


def _fuente_nativa(repo, folio, entrada):
    if not isinstance(entrada, dict):
        raise ValueError("La operación requiere las referencias de la transacción nativa.")
    via = entrada.get("via", "estandar")
    if via != "estandar":
        raise ErrorConvivencia(f"La vía {via!r} requiere el procedimiento nativo.", codigo="VIA_NATIVA_PENDIENTE")
    rama = entrada.get("rama_fuente", repo.rama)
    match = re.fullmatch(RAMA, rama or "")
    postuma = entrada.get("postuma", False)
    actor = entrada.get("integrador", entrada.get("actor"))
    if (not match or match[1] != _id(folio) or not re.fullmatch(ACTOR, actor or "")
            or type(postuma) is not bool):
        raise ValueError("Rama fuente, folio o actor integrador inválidos.")
    if postuma and folio.startswith("G"):
        raise ErrorConvivencia("Ramas §5 documenta la vía póstuma S y el pin admite G/S.", codigo="DISCREPANCIA_PIN")
    if ((postuma and actor == match[2])
            or (not postuma and (actor != match[2] or entrada.get("actor") != actor))
            or entrada.get("transaccion") != match[2]):
        raise ValueError("El actor integrador y la transacción fuente no corresponden a la vía.")
    punta = repo.commit_ref("refs/heads/" + rama)
    fuente = repo.en_arbol(punta, historico=True)
    plan = fuente.plan(folio)
    if plan["estado"] != "Activo":
        raise ValueError("El plan de la rama fuente debe permanecer Activo.")
    return fuente, plan, rama, actor, postuma


def _pendientes_trabajo(raiz, indice):
    """Compara archivos e índice en bytes sin invocar filtros ni refrescarlo."""
    deltas = []
    for ruta, (modo, blob) in indice.entradas.items():
        imagen = _leer_trabajo(raiz, ruta)
        if imagen is None or imagen[0] != modo:
            deltas.append(ruta)
            continue
        datos = imagen[1]
        algoritmo = hashlib.sha256 if len(blob) == 64 else hashlib.sha1
        if algoritmo(f"blob {len(datos)}\0".encode() + datos).hexdigest() != blob:
            deltas.append(ruta)
    nuevos = _git(raiz, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8")
    return deltas + [ruta for ruta in nuevos.split("\0") if ruta and not re.fullmatch(
        r"(?:.*/)?gobernanza/sesiones/intervenciones/[^/]+\.jsonl", ruta)]


def _comprobar_limpieza(raiz, commit):
    indice = LectorArbol(raiz, "staged")
    if indice.entradas != LectorArbol(raiz, commit).entradas or _pendientes_trabajo(raiz, indice):
        raise ValueError(f"El worktree no está limpio en la punta comprobada: {raiz}.")


def _topologia(repo, rama, fuente, *, postuma, despues=False, esperada=None):
    from .acuerdos import _git_worktrees_nativos

    inventario = _git_worktrees_nativos(repo)
    propietario = inventario.get("refs/heads/" + rama)
    if postuma:
        if repo.rama != "main":
            raise ValueError("La vía póstuma se coteja desde main.")
        topologia = "separate_worktrees"
    elif repo.rama == rama and not inventario.get("refs/heads/main") and not despues:
        topologia = "same_worktree"
    elif repo.rama == "main" and despues and esperada == "same_worktree" and propietario is None:
        topologia = "same_worktree"
    elif repo.rama == "main" and propietario is not None and propietario[0] != repo.raiz:
        topologia = "separate_worktrees"
    else:
        raise ValueError("No se pudo cotejar la topología de la fuente y del worktree integrador.")
    if topologia == "separate_worktrees" and propietario is not None:
        raiz, cabeza = propietario
        if cabeza != fuente:
            raise ValueError("La fuente materializada está desfasada de su rama.")
        _comprobar_limpieza(raiz, fuente)
    return topologia


def _rutas_cierre_nativo(plan, rutas):
    obligatorias = {plan["ruta"], plan["estado_modulo"], plan["evidencia"]}
    if (not isinstance(rutas, list) or not all(isinstance(r, str) for r in rutas)
            or len(set(rutas)) != len(rutas) or not obligatorias <= set(rutas)
            or set(rutas) - (obligatorias | {plan["continuidad"]})):
        raise ErrorConvivencia("El cierre estándar exige la triada exacta del módulo y sólo admite su continuidad.",
                               plan["ruta"], "DISCREPANCIA_PIN")
    return sorted(rutas)


def _diff_integracion(repo, base, fuente):
    from .inicio import _rutas_cambiadas

    repo.git("merge-base", "--is-ancestor", base, fuente)
    antes, despues = LectorArbol(repo.raiz, base), LectorArbol(repo.raiz, fuente)
    rutas = _rutas_cambiadas(antes, despues)
    if not rutas:
        raise ValueError("La fuente no tiene un diff propio respecto de la base.")
    binario = _git(repo.raiz, "diff", "--binary", "--no-ext-diff", "--no-textconv", f"{base}..{fuente}", "--")
    return rutas, huella_bytes(binario)


def _candidato_nativo(repo, fuente, plan, rama, actor, postuma, base, rutas_cierre, *, topologia):
    rutas, huella = _diff_integracion(repo, base, fuente.commit)
    return {"schema_version": 1, "project_id": repo.proyecto, "profile_version": 2,
            "session_id": actor, "folio": plan["folio"], "root": str(repo.comun),
            "git_common_dir": str(repo.comun), "integrator_root": str(repo.raiz),
            "topology": topologia, "branch": rama, "source_sha": fuente.commit,
            "base_sha": base, "source_tree": _arbol_commit(repo, fuente.commit),
            "diff_sha256": huella, "rutas": rutas, "plan_path": plan["ruta"], "posthumous": postuma,
            "closure_paths": _rutas_cierre_nativo(plan, rutas_cierre),
            "closure_message": f"cierre: integrar {plan['folio']} ({plan['modulo']})"}


def _inventario_permisos(repo, propia):
    base = repo.raiz / ".heimdall/runtime/integration"
    for directorio in (repo.raiz / ".heimdall", base.parent, base):
        if directorio.is_symlink() or (directorio.exists() and not directorio.is_dir()):
            raise ValueError("El inventario de integración atraviesa una ruta insegura.")
    if not base.exists():
        return
    for actor in base.iterdir():
        if actor.is_symlink():
            raise ValueError("El inventario de permisos contiene una ruta enlazada.")
        if not actor.is_dir():
            continue
        niveles = [actor]
        for folio in actor.iterdir():
            if folio.is_symlink():
                raise ValueError("El inventario de permisos contiene una ruta enlazada.")
            if folio.is_dir():
                niveles.append(folio)
        for carpeta in niveles:
            ruta = (carpeta / "heimdall.json").relative_to(repo.raiz).as_posix()
            if ruta == propia:
                continue
            otro = repo.runtime(ruta)
            if otro is None:
                continue
            if otro.get("phase") not in _FASES_PERMISO or not isinstance(otro.get("integrator_root"), str):
                raise ValueError(f"No se puede determinar la fase o raíz del permiso: {ruta}.")
            if otro["integrator_root"] == str(repo.raiz) and otro["phase"] not in {"complete", "resolved"}:
                raise ValueError(f"Otro permiso de integración sigue no terminal: {ruta}.")


_FASES_PERMISO = {"approved", "merged", "suite-failed", "suite-green", "reverted", "resolved", "complete"}


def _ruta_permiso(actor, folio):
    return f".heimdall/runtime/integration/{actor}/{folio}/heimdall.json"


def _leer_permiso(repo, actor, folio):
    ruta = _ruta_permiso(actor, folio)
    _inventario_permisos(repo, ruta)
    permiso = repo.runtime(ruta)
    if permiso is None:
        raise ValueError(f"Falta el permiso de integración canónico: {ruta}.")
    if any(campo in permiso for campo in ("companion_plan_paths", "companion_closure_paths")):
        raise ErrorConvivencia("El cierre conjunto requiere el procedimiento nativo.", ruta, "VIA_NATIVA_PENDIENTE")
    return permiso, ruta


def _comprobar_permiso(permiso, candidato, *, merge=False):
    campos = ("schema_version", "project_id", "profile_version", "session_id", "folio", "root",
              "git_common_dir", "integrator_root", "topology", "branch", "source_sha", "base_sha",
              "diff_sha256", "plan_path", "closure_message")
    fase = permiso.get("phase")
    if (any(permiso.get(k) != candidato[k] for k in campos)
            or type(permiso.get("schema_version")) is not int or type(permiso.get("profile_version")) is not int
            or permiso.get("posthumous", False) is not candidato["posthumous"]
            or sorted(permiso.get("closure_paths", [])) != candidato["closure_paths"]
            or not isinstance(permiso.get("approval"), str) or not permiso["approval"].strip()
            or fase not in _FASES_PERMISO or (merge and fase != "approved")):
        raise ValueError("El permiso no corresponde a la fase, actor o candidato exactos.")
    inicio, fin = (datetime.fromisoformat(permiso[k].replace("Z", "+00:00"))
                   for k in ("issued_at", "expires_at"))
    ahora = datetime.now(timezone.utc)
    if (inicio.tzinfo is None or fin.tzinfo is None or not timedelta(0) < fin - inicio <= timedelta(minutes=15)
            or inicio > ahora + timedelta(minutes=1) or (merge and ahora >= fin)):
        raise ValueError("La ventana nativa del permiso no es válida para esta fase.")


def _exigir_informe_nativo(repo, folio, informe, autoridad):
    if (not isinstance(informe, dict) or informe.get("schema") != 1 or informe.get("codigo") != 0
            or informe.get("perfil_operacion") != PERFIL or informe.get("etapa") != "entrega"
            or informe.get("sesion") != folio or informe.get("pruebas_aprobadas") is not True
            or informe.get("huella_acuerdo") != autoridad["huella_acuerdo"]
            or (repo.commit is not None and informe.get("arbol", {}).get("commit") != repo.commit)):
        raise ValueError("Se requiere un informe verde de entrega ligado a la fuente y acuerdo exactos.")
    vigente = evidencia_vigente(repo.raiz, informe, arbol=repo.arbol)
    if vigente["codigo"] or vigente.get("vigente") is not True:
        raise ValueError(f"El informe de entrega no es vigente: {vigente.get('errores', [])}.")


def _evaluar_nativo(repo, folio, informe, entrada):
    from .acuerdos import preflight_nativo

    datos = preflight_nativo(repo, folio, entrada)
    _exigir_informe_nativo(repo, folio, informe, datos)
    salida = _salida("evaluar_entrega")
    salida.update(perfil_operacion=PERFIL, entrega_lista=True, arbol=repo.arbol, acuerdo=datos)
    return salida


def _preparar_nativo(repo, folio, informe, entrada):
    from .acuerdos import preflight_nativo

    fuente, plan, rama, actor, postuma = _fuente_nativa(repo, folio, entrada)
    topologia = _topologia(repo, rama, fuente.commit, postuma=postuma)
    _comprobar_limpieza(repo.raiz, repo.head)
    base = repo.commit_ref("refs/heads/main")
    rutas = entrada.get("rutas_cierre", [plan["ruta"], plan["evidencia"], plan["estado_modulo"]])
    candidato = _candidato_nativo(repo, fuente, plan, rama, actor, postuma, base, rutas, topologia=topologia)
    autoridad = preflight_nativo(fuente, folio, entrada, rutas=candidato["rutas"], fase="integracion")
    _exigir_informe_nativo(fuente, folio, informe, autoridad)
    candidato.update(huella_acuerdo=autoridad["huella_acuerdo"], huella_informe=informe["huella_informe"])
    candidato["huella_candidato"] = huella_datos(candidato)
    decision = "pendiente"
    if entrada.get("comprobar_permiso"):
        permiso, _ = _leer_permiso(repo, actor, folio)
        _rutas_cierre_nativo(plan, permiso.get("closure_paths"))
        _comprobar_permiso(permiso, candidato, merge=True)
        decision = "cotejada"
    else:
        _inventario_permisos(repo, _ruta_permiso(actor, folio))
    if (repo.commit_ref("refs/heads/main") != base
            or repo.commit_ref("refs/heads/" + rama) != fuente.commit):
        raise ValueError("Las referencias del candidato avanzaron durante el cotejo.")
    salida = _salida("preparar_cierre")
    salida.update(perfil_operacion=PERFIL, candidato=candidato, inicio_integracion_cotejado=decision == "cotejada",
                  entrega_lista=True, decision=decision)
    return salida


def _suite_nativa(repo, plan, referencia, actor, cabeza, comando=None):
    from .verificacion import cotejar_registro_nativo

    trabajo = repo.en_arbol("worktree")
    suite = cotejar_registro_nativo(trabajo, plan, referencia)
    casos = suite.get("casos")
    partes = suite.get("comando")
    if (suite.get("tipo") != "suite" or suite.get("version") != cabeza or suite.get("actor") != actor
            or suite.get("estado") != "pasa" or type(suite.get("exit")) is not int or suite["exit"] != 0
            or not isinstance(casos, dict) or not casos
            or any(not isinstance(k, str) or not k.strip() or v != "aprobado" for k, v in casos.items())
            or not isinstance(partes, list) or not partes or any(not isinstance(p, str) or not p for p in partes)
            or not isinstance(suite.get("entorno"), dict) or not suite["entorno"]
            or any(not isinstance(suite.get(k), str) or not suite[k].strip()
                   for k in ("id", "fecha", "referencia", "salida"))):
        raise ValueError("La suite post-main no acredita verde del actor sobre el SHA efectivo.")
    if datetime.fromisoformat(suite["fecha"].replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("La fecha de la suite post-main requiere zona horaria.")
    if comando is not None and " ".join(partes) != comando:
        raise ValueError("El comando de la suite difiere del registrado en el permiso.")
    return suite


def _comprobar_reversion(repo, plan, permiso, candidato, integracion, entrada):
    revert = _oid(permiso.get("revert_sha"))
    if (_padres_commit(repo, revert) != [integracion]
            or _arbol_commit(repo, revert) != _arbol_commit(repo, candidato["base_sha"])
            or permiso.get("suite_head") != integracion or permiso.get("suite_result") != "failed"
            or permiso.get("retest_result") != "passed" or permiso.get("retest_head") != revert):
        raise ValueError("La reversión o el retest no restauran el primer padre del merge.")
    repo.git("merge-base", "--is-ancestor", revert, repo.head)
    _suite_nativa(repo, plan, entrada.get("suite"), candidato["session_id"], revert)
    salida = _fallo("confirmar_cierre", "Se observó la reversión exacta y su retest; se conserva el claim.",
                    plan["ruta"], "INTEGRACION_REVERTIDA")
    salida.update(perfil_operacion=PERFIL, estado_cierre="revertido", merge=integracion, reversion=revert)
    return salida


def _comprobar_merge(repo, permiso, candidato, integracion):
    base, fuente = candidato["base_sha"], candidato["source_sha"]
    if (_padres_commit(repo, integracion) != [base, fuente]
            or _arbol_commit(repo, integracion) != candidato["source_tree"]
            or (permiso.get("merge_sha"), permiso.get("merge_parent1"), permiso.get("merge_parent2"))
            != (integracion, base, fuente)):
        raise ValueError("El merge observado no tiene los dos padres ordenados y el árbol aprobado.")
    repo.git("merge-base", "--is-ancestor", integracion, repo.head)


def _comprobar_integracion_vigente(repo, candidato, merge, cabeza_suite, plan):
    from .inicio import _transicion_nativa

    activo = repo.en_arbol(cabeza_suite, historico=True).plan(plan["folio"])
    _transicion_nativa(plan, activo, "Activo")
    previos = repo.git("rev-list", "--first-parent", f"{merge}..{cabeza_suite}").decode("ascii").splitlines()
    arbol_previo = _arbol_commit(repo, candidato["base_sha"])
    if any(_arbol_commit(repo, sha) == arbol_previo for sha in previos):
        raise ValueError("La historia posterior a la integración contiene una restauración del árbol base.")


def _cierre_cotejado(repo, autoridad, permiso, arbol, *, suite, lote=None):
    from .inicio import (_cabecera_lote, _conciliar_imagenes, _diff_lote,
                         _rutas_cambiadas, _transicion_nativa)

    cabeza = permiso["suite_head"]
    folio = autoridad["plan"]["folio"]
    anterior = repo.en_arbol(cabeza, historico=True)
    previo = anterior.plan(folio)
    if previo["estado"] != "Activo":
        raise ValueError("El plan de la punta verificada por la suite debe permanecer Activo.")
    _transicion_nativa(previo, repo.plan(folio), "Completado")
    rutas = _rutas_cambiadas(anterior.lector, repo.lector)
    if rutas != sorted(permiso["closure_paths"]):
        raise ValueError("El diff completo no coincide con las rutas del cierre estándar.")
    imagenes = _diff_lote(anterior.lector, repo.lector, rutas)
    if any(i["despues"] is None for i in imagenes.values()):
        raise ValueError("El cierre estándar no admite borrados.")
    criterio = {k: v for k, v in permiso.items() if k not in {"phase", "closure_sha"}}
    evidencias = {"huella_permiso": huella_datos(criterio), "suite": suite}
    nombre = _cabecera_lote(repo, autoridad, folio, "cierre", cabeza, imagenes,
                            mensaje=permiso["closure_message"], evidencias=evidencias)
    if lote is not None and lote != nombre:
        raise ValueError("El cierre observado difiere del lote de cierre planificado.")
    _conciliar_imagenes(repo, folio, nombre, arbol)
    if arbol == "staged" and _pendientes_trabajo(repo.raiz, repo.lector):
        raise ValueError("Quedan cambios unstaged o nuevos fuera del lote de cierre.")
    return nombre


def _confirmar_nativo(repo, folio, integracion, entrada):
    from .acuerdos import preflight_nativo

    if repo.rama != "main" or repo.head != repo.commit_ref("refs/heads/main"):
        raise ValueError("La conciliación del cierre se hace sobre el worktree dueño de main.")
    integracion = _oid(integracion)
    fuente, plan, rama, actor, postuma = _fuente_nativa(repo, folio, entrada)
    permiso, ruta_permiso = _leer_permiso(repo, actor, folio)
    topologia = _topologia(repo, rama, fuente.commit, postuma=postuma, despues=True,
                           esperada=permiso.get("topology"))
    _rutas_cierre_nativo(plan, permiso.get("closure_paths"))
    candidato = _candidato_nativo(repo, fuente, plan, rama, actor, postuma, _oid(permiso.get("base_sha")),
                                  entrada.get("rutas_cierre", permiso["closure_paths"]), topologia=topologia)
    _comprobar_permiso(permiso, candidato)
    _comprobar_merge(repo, permiso, candidato, integracion)
    autoridad = preflight_nativo(fuente, folio, entrada, rutas=candidato["rutas"], fase="integracion")
    fase = permiso["phase"]
    if fase in ("reverted", "resolved"):
        return _comprobar_reversion(repo, plan, permiso, candidato, integracion, entrada)
    if fase not in ("suite-green", "complete") or permiso.get("suite_result") != "passed":
        salida = _fallo("confirmar_cierre", f"Fase {fase!r} sin suite verde verificable.",
                        plan["ruta"], "INTEGRACION_PENDIENTE")
        salida.update(perfil_operacion=PERFIL, estado_cierre="pendiente", merge=integracion)
        return salida
    cabeza_suite = _oid(permiso.get("suite_head"))
    repo.git("merge-base", "--is-ancestor", integracion, cabeza_suite)
    _comprobar_integracion_vigente(repo, candidato, integracion, cabeza_suite, plan)
    cierre = entrada.get("commit_cierre")
    cabeza_esperada = _oid(cierre) if cierre is not None else cabeza_suite
    if cabeza_esperada != repo.head:
        raise ErrorConvivencia("Main avanzó; repite la suite o sigue la vía nativa de cierre tardío.",
                               codigo="VIA_NATIVA_PENDIENTE")
    comando = permiso.get("suite_command")
    if not isinstance(comando, str) or not comando.strip():
        raise ValueError("El permiso no conserva el comando nativo de la suite.")
    suite = entrada.get("suite")
    _suite_nativa(repo, plan, suite, actor, cabeza_suite, comando)
    salida = _salida("confirmar_cierre")
    salida.update(perfil_operacion=PERFIL, estado_cierre="pendiente", merge=integracion,
                  permiso=ruta_permiso, integracion_confirmada=True)
    if cierre is not None:
        if not isinstance(entrada.get("lote_cierre"), dict):
            raise ValueError("El commit de cierre requiere el lote cotejado antes del guardado.")
        if fase != "complete" or permiso.get("closure_sha") != cierre:
            raise ValueError("Falta el permiso terminal ligado al commit exacto de cierre.")
        salida["lote"] = _cierre_cotejado(repo, autoridad, permiso, cierre, suite=suite, lote=entrada.get("lote_cierre"))
        salida.update(estado_cierre="completado", commit_cierre=cierre)
    elif entrada.get("comprobar_cierre"):
        if fase != "suite-green":
            raise ValueError("La preparación staged exige permiso en suite-green.")
        indice = repo.en_arbol("staged")
        salida["lote"] = _cierre_cotejado(indice, autoridad, permiso, "staged", suite=suite, lote=entrada.get("lote_cierre"))
        salida["estado_cierre"] = "preparado"
    return salida


def conciliar_lote_cierre(repo, folio, lote, arbol, entrada):
    from .inicio import _respuesta_lote

    integracion = _oid(entrada.get("integracion"))
    adicionales = ({"comprobar_cierre": True} if arbol == "staged" else {"commit_cierre": arbol})
    salida = _confirmar_nativo(repo, folio, integracion, dict(entrada, lote_cierre=lote, **adicionales))
    if salida["codigo"]:
        return salida
    return _respuesta_lote("conciliar_guardado", lote, guardado=repo.commit, estado_cierre=salida["estado_cierre"])
