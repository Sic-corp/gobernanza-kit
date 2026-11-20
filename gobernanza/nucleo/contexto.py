"""Contexto por sesión, funcionalidad o ruta; F-0101@r1."""

from collections import deque
from pathlib import Path
import re

from .arboles import ErrorArbol, commit_lectura, materializar
from .convivencia import ErrorConvivencia, informe_error, seleccionar_perfil
from .documentos import cargar, informe_nativo
from .modelo import coincide, diagnostico, referencia, resultado, unicos


def contexto(raiz, *, sesion=None, funcionalidad=None, ruta=None, arbol="worktree",
             historico=False, integrada=False, version=None):
    opciones = [v for v in (sesion, funcionalidad, ruta) if v is not None]
    versionada = integrada or version is not None
    if (type(integrada) is not bool or any(not isinstance(v, str) or not v for v in opciones)
            or len(opciones) > 1 or (not versionada and len(opciones) != 1)
            or (versionada and (sesion is not None or arbol != "worktree" or historico))
            or (integrada and (funcionalidad is None or version is not None))
            or (version is not None and (not isinstance(version, str)
                or re.fullmatch(r"V[1-9][0-9]*\.(?:0[0-9]|[1-9][0-9]+)", version) is None))):
        return resultado("contexto", [diagnostico("USO", ".", "Selectores compatibles",
                         "Indica sesión, F o ruta; usa integrada con F, o una versión V1.00 con filtro opcional.",
                         "Usa una consulta por árbol Git o por versión de aplicación.")], codigo=2)
    if versionada:
        try:
            return _contexto_versionado(raiz, funcionalidad, ruta, version)
        except (TypeError, ValueError, OSError) as exc:
            return _error_version("HISTORIAL_VERSIONADO", str(exc) or type(exc).__name__)
    try:
        nativo = seleccionar_perfil(raiz, arbol, historico=historico)
        if nativo is not None:
            return informe_nativo(nativo, "contexto", sesion=sesion, funcionalidad=funcionalidad, ruta=ruta)
        raiz_documental = Path(raiz)
        es_git = (raiz_documental / ".git").exists()
        if es_git:
            from .registro_sdd import auditar
            errores = auditar(raiz, arbol)
            if errores:
                return resultado("contexto", errores)
        if arbol == "worktree" and (not es_git or not (raiz_documental / "sdd/registro").exists()):
            return _contexto_estandar(cargar(raiz), sesion, funcionalidad, ruta)
        with materializar(raiz, arbol) as copia:
            return _contexto_estandar(cargar(copia.raiz), sesion, funcionalidad, ruta)
    except (ErrorConvivencia, ErrorArbol) as exc:
        return informe_error("contexto", exc)
    except (TypeError, ValueError, OSError) as exc:
        return resultado("contexto", [diagnostico("RAIZ_INVALIDA", str(raiz), "Raíz de proyecto legible",
                                              str(exc), "Indica una carpeta de proyecto válida.")])


def _revisiones_vigentes(doc, revision):
    return [r for r in doc.datos["revisiones"] if r <= revision]


def _contexto_estandar(repo, sesion, funcionalidad, ruta):
    cola = deque()
    externas_pertinentes = {}
    pendientes_pertinentes = []

    def agregar(ref, razon, origen="consulta", propuesta=False):
        anteriores = len(repo.pendientes)
        resuelto = repo.resolver(ref, origen, propuesta)
        pendientes_pertinentes.extend(repo.pendientes[anteriores:])
        if isinstance(ref, str) and ref in repo.externas:
            externas_pertinentes[ref] = repo.externas[ref]
        if resuelto is not None:
            cola.append((resuelto[0], resuelto[1], razon))

    if not repo.errores:
        if ruta is not None:
            if repo.segura(ruta) is not None:
                for doc in repo.documentos:
                    for objeto in doc.datos.get("objetos", []):
                        if coincide(ruta, objeto):
                            agregar(doc.ref(), f"objeto propio {ruta}", doc.ruta)
                    for compartido in doc.datos.get("objetos_compartidos", []):
                        if coincide(ruta, compartido["ruta"]):
                            agregar(doc.ref(), f"propietario del objeto compartido {ruta}", doc.ruta)
                            for consumidor in compartido["consumidores"]:
                                agregar(consumidor, f"consumidor de {ruta}", doc.ruta)
                if not cola:
                    repo.error("OBJETO_SIN_CONTRATO", ruta, f"No hay propietario declarado para {ruta}.")
        else:
            ref = sesion if sesion is not None else funcionalidad
            partes = referencia(ref)
            prefijo = ("S", "G") if sesion is not None else ("F",)
            if partes is None or not partes[0].startswith(prefijo):
                repo.error("CONSULTA_INVALIDA", "consulta", f"El selector no admite {ref!r}.")
            else:
                agregar(ref, f"consulta por {'sesión' if sesion is not None else 'funcionalidad'}")

    incluidos = {}
    while cola:
        doc, revision, razon = cola.popleft()
        ref = doc.ref(revision)
        if ref in incluidos:
            if razon not in incluidos[ref]["razones"]:
                incluidos[ref]["razones"].append(razon)
            continue
        incluidos[ref] = doc.contrato(revision, [razon])
        for relacion, propuesta, campo in repo.relaciones(doc):
            # La lista global del módulo y las sesiones que mencionan una F no
            # amplían el contexto de esa F a todo el historial del proyecto.
            if campo in {"sesiones", "consumidores"} or (doc.tipo == "modulo" and campo.startswith("funcionalidades")):
                continue
            agregar(relacion, f"{campo} de {ref}", doc.ruta, propuesta)
        if doc.tipo == "funcionalidad":
            for modulo in repo.documentos:
                for compartido in modulo.datos.get("objetos_compartidos", []):
                    consumidores = [repo.resolver(c, modulo.ruta) for c in compartido["consumidores"]]
                    if any(c is not None and c[0].ref(c[1]) == ref for c in consumidores):
                        agregar(modulo.ref(), f"propietario compartido para {ref}", modulo.ruta)
                        for consumidor in compartido["consumidores"]:
                            agregar(consumidor, f"consumidor de {compartido['ruta']} con {ref}", modulo.ruta)

    salida = resultado("contexto", repo.errores, pendientes_pertinentes)
    salida["contratos"] = list(incluidos.values())
    refs = set(incluidos)
    heredar = repo.config.get("versionado_aplicacion") is True
    for contrato in salida["contratos"]:
        doc, revision = repo.resolver(contrato["referencia"], contrato["ruta"])
        if heredar and doc.tipo == "funcionalidad":
            for anterior in _revisiones_vigentes(doc, revision):
                refs.add(doc.ref(anterior))
                salida["criterios"].extend(doc.criterios(anterior))
        else:
            salida["criterios"].extend(doc.criterios(revision))
    salida["criterios"] = unicos(salida["criterios"])
    salida["pruebas_declaradas"] = [p for p in repo.pruebas if p["criterio"].split("/", 1)[0] in refs]
    salida["referencias_externas"] = [dict(origen, ref=ref) for ref, origen in externas_pertinentes.items()]
    return salida


def _error_version(codigo, mensaje):
    return resultado("contexto", [diagnostico(
        codigo, "sdd/entregas/aplicacion.json", "Historial integrado y funcionalidad inequívoca",
        mensaje, "Concilia el historial de main o consulta una versión histórica por su V.",
    )])


def _identidad(ref):
    return ref.split("@", 1)[0]


def _identidades_del_cambio(cambio):
    return {_identidad(ref) for ref in cambio["funcionalidades"] + cambio.get("funcionalidades_anteriores", [])}


def _cambios_de(registro, identidad):
    return [cambio for cambio in registro["cambios"] if identidad in _identidades_del_cambio(cambio)]


def _ficha_integrada(repo, ref):
    candidatos = repo.por_id.get(_identidad(ref), [])
    if len(candidatos) != 1:
        return None
    ficha = candidatos[0]
    if ficha.ref() != ref or ficha.datos.get("estado") in {"borrador", "propuesta", "retirada", "retirado", "deprecada", "cancelada"}:
        return None
    return ficha


def _datos_ficha(repo, ficha, historial, commit):
    ref = ficha.ref()
    revision = ficha.datos["revision_actual"]
    resuelto = repo.resolver(ficha.datos["modulo"], ficha.ruta)
    if resuelto is None:
        raise ValueError(f"No existe un módulo dueño local para la ficha integrada {ref}.")
    modulo, version_modulo = resuelto
    compartidos = [
        dict(ruta=objeto["ruta"], modulo=spec.id, spec=spec.ruta)
        for spec in repo.documentos for objeto in spec.datos.get("objetos_compartidos", [])
        if ref in objeto["consumidores"] or ficha.id in objeto["consumidores"]
    ]
    revisiones = _revisiones_vigentes(ficha, revision)
    refs_heredadas = {ficha.ref(r) for r in revisiones if r != revision}
    directas = []
    heredadas = []
    for prueba in repo.pruebas:
        vinculo = prueba["criterio"].split("/", 1)[0]
        if vinculo == ref:
            directas.append(prueba)
        elif vinculo in refs_heredadas:
            heredadas.append(prueba)
    primera = next(registro["version"] for registro in historial if ref in registro["funcionalidades"])
    entrega = next((registro for registro in reversed(historial) if registro["tipo"] != "linea_base"
                   and (ref in registro["funcionalidades"] or _cambios_de(registro, ficha.id))), None)
    ultima = None if entrega is None else {
        **{clave: entrega[clave] for clave in ("version", "commit", "sesion", "evidencia")},
        "cambios": _cambios_de(entrega, ficha.id),
    }
    traza = dict(funcionalidad=ref, modulo=modulo.id, spec=modulo.ruta, ficha=ficha.ruta,
                 commit_ficha=commit, objetos_propios=ficha.datos.get("objetos", []),
                 objetos_compartidos=compartidos, pruebas_directas=directas, pruebas_heredadas=heredadas,
                 primera_version=primera, ultima_entrega=ultima,
                 evidencias_por_revision=ficha.datos.get("evidencias_por_revision", {}))
    contratos = [ficha.contrato(razones=["funcionalidad integrada"]),
                 modulo.contrato(version_modulo, razones=["módulo dueño de la funcionalidad"])]
    criterios = [criterio for r in revisiones for criterio in ficha.criterios(r)]
    return traza, contratos, criterios


def _datos_traza(raiz, repo, ref, registros):
    ficha = _ficha_integrada(repo, ref)
    if ficha is not None:
        return _datos_ficha(repo, ficha, registros, registros[-1]["commit"])
    entrega = next(registro for registro in reversed(registros) if ref in registro["funcionalidades"])
    with materializar(raiz, entrega["commit"]) as copia:
        anterior = cargar(copia.raiz)
        ficha = _ficha_integrada(anterior, ref)
        if anterior.errores or ficha is None:
            raise ValueError(f"La versión {entrega['version']} no contiene la ficha integrada {ref}.")
        return _datos_ficha(anterior, ficha, registros, entrega["commit"])


def _contexto_versionado(raiz, funcionalidad, ruta, version):
    from .versiones import historial

    punta = commit_lectura(raiz, "refs/heads/main")
    if seleccionar_perfil(raiz, punta, historico=True) is not None:
        return _error_version("PERFIL_VERSIONADO", "La consulta por V corresponde al perfil estándar.")
    registros = historial(raiz, punta)
    if not registros:
        return _error_version("VERSIONADO_AUSENTE", "El proyecto no tiene versiones de aplicación integradas.")
    if version is None and registros[-1]["commit"] != punta:
        from .versiones import comprobar_vigencia
        comprobar_vigencia(raiz, registros[-1]["commit"], punta)
    if version is not None:
        posiciones = [i for i, registro in enumerate(registros) if registro["version"] == version]
        if not posiciones:
            return _error_version("VERSION_NO_INTEGRADA", f"No existe la versión integrada {version}.")
        registros = registros[:posiciones[0] + 1]

    seleccion = registros[-1]
    efectivas = {_identidad(ref): ref for registro in registros for ref in registro["funcionalidades"]}
    if funcionalidad is not None:
        partes = referencia(funcionalidad)
        ref = efectivas.get(partes[0]) if partes else None
        if not ref or (partes[1] is not None and funcionalidad != ref):
            return _error_version("F_NO_INTEGRADA", f"{funcionalidad} no está vigente en {seleccion['version']}.")
        refs = [ref]
        cambios = _cambios_de(seleccion, partes[0])
    elif ruta is not None:
        refs = list(efectivas.values())
        cambios = [cambio for cambio in seleccion["cambios"] if cambio["ruta"] == ruta]
    else:
        refs = seleccion["funcionalidades"]
        if seleccion.get("meta"):
            refs = [efectivas[_identidad(ref)] for ref in seleccion["meta"]["requisitos"]]
        cambios = seleccion["cambios"]

    ids_cambiadas = {identidad for cambio in cambios for identidad in _identidades_del_cambio(cambio)}
    with materializar(raiz, seleccion["commit"]) as copia:
        repo = cargar(copia.raiz)
        if ruta is not None:
            repo.segura(ruta)
        salida = resultado("contexto", repo.errores)
        if salida["codigo"]:
            return salida
        trazas = []
        contratos = []
        criterios = []
        for ref in refs:
            traza, fichas, criterios_f = _datos_traza(raiz, repo, ref, registros)
            if ruta is not None:
                objetos = traza["objetos_propios"] + [obj["ruta"] for obj in traza["objetos_compartidos"]]
                afecta = any(coincide(ruta, objeto) for objeto in objetos)
                if not afecta and _identidad(ref) not in ids_cambiadas:
                    continue
            trazas.append(traza)
            contratos.extend(fichas)
            criterios.extend(criterios_f)
    if ruta is not None and not (trazas or cambios):
        return _error_version("OBJETO_SIN_CONTRATO", f"No hay objeto declarado o cambiado para {ruta} en {seleccion['version']}.")
    salida.update(
        resumen=f"{seleccion['version']} · {seleccion['commit']} · {len(trazas)} funcionalidad(es).",
        version_aplicacion=dict(seleccion, cambios=cambios), trazas_funcionales=trazas,
        contratos=unicos(contratos), criterios=unicos(criterios),
        pruebas_declaradas=unicos([p for t in trazas for p in t["pruebas_directas"] + t["pruebas_heredadas"]]),
    )
    return salida
