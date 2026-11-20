"""Consultas y adopción explícita del registro documental V3."""

from functools import lru_cache
import hashlib
from itertools import groupby
import re

from .acuerdos import _capturar
from .arboles import LectorArbol, _git, _leer_trabajo, commit_lectura, materializar
from .documentos import cargar, json_estricto
from .inicio import _escribir_bytes
from .modelo import diagnostico, referencia, resultado, unicos
from .modelo_sdd import leer, seccion, validar_grafo
from .registro_sdd import cargar_registro, listar_operaciones
from .versiones import historial


INDICE = "sdd/indice.md"
MARCA = "<!-- gobernanza:indice-sdd-v3 -->\n"
REGISTRO = "sdd/registro/"
TIPOS = {
    "spec": "Specs", "modulo": "Módulos", "funcionalidad": "Funcionalidades",
    "sesion": "Sesiones", "enmienda": "Enmiendas",
}


def _fallo(operacion, codigo, ruta, mensaje):
    return resultado(operacion, [diagnostico(
        codigo, ruta, "Registro documental y procedencia válidos", str(mensaje),
        "Corrige la referencia o el archivo indicado y vuelve a ejecutar la operación.",
    )])


def _vista(raiz, arbol):
    lector = LectorArbol(raiz, arbol)
    elegido = lector.commit or arbol
    ancla = lector.commit or commit_lectura(lector.raiz, "HEAD")
    operaciones = listar_operaciones(lector.raiz, elegido)
    if lector.commit is None and commit_lectura(lector.raiz, "HEAD") != ancla:
        raise ValueError("HEAD cambió mientras se cotejaba el registro documental.")
    documentos = cargar_registro(lector.raiz, ancla)
    return lector, documentos, operaciones, ancla


def _vinculos(datos):
    secciones = datos.get("secciones", [])
    if datos["tipo"] == "spec":
        secciones = [f"{datos['ref']}#{nombre}" for nombre in secciones]
    modulo = [datos["modulo"]] if "modulo" in datos else []
    origen = [datos["origen"]] if "origen" in datos else []
    return (modulo + datos.get("modulos", []) + datos.get("funcionalidades", []) + secciones
            + datos.get("resultantes", []) + datos.get("dependencias", []) + origen)


def _texto_indice(documentos):
    lineas = [MARCA.rstrip("\n"), "# Índice del registro documental", ""]
    ordenados = sorted((documento[0] for documento in documentos.values()),
                       key=lambda datos: (tuple(TIPOS).index(datos["tipo"]), datos["ref"]))
    for tipo, grupo in groupby(ordenados, key=lambda datos: datos["tipo"]):
        lineas.extend([f"## {TIPOS[tipo]}", ""])
        for datos in grupo:
            ref = datos["ref"]
            texto = f"- [{ref}](registro/{ref}.md) · {datos['estado']}"
            vinculados = ", ".join(f"`{v}`" for v in _vinculos(datos))
            lineas.append(f"{texto} · {vinculados}" if vinculados else texto)
        lineas.append("")
    return "\n".join(lineas)


def generar_indice(raiz, *, comprobar=False, escribir=False, arbol="worktree"):
    """Proyecta metadatos validados y opcionalmente guarda sólo el índice generado."""
    operacion = "indice-sdd"
    if (type(comprobar) is not bool or type(escribir) is not bool or (comprobar and escribir)
            or (escribir and arbol != "worktree")):
        return _fallo(operacion, "INDICE_USO", INDICE,
                      "Usa comprobar o escribir de forma exclusiva. Escribir exige el árbol de trabajo.")
    try:
        lector, documentos, _, _ = _vista(raiz, arbol)
        errores = validar_grafo(documentos)
        if errores:
            return resultado(operacion, errores)
        texto = _texto_indice(documentos)
        lector.comprobar_ruta(INDICE)
        entrada = (_leer_trabajo(lector.raiz, INDICE) if arbol == "worktree" else lector.entrada(INDICE))
        contenido = texto.encode("utf-8")
        vigente = entrada is not None and entrada[1] == contenido
        if escribir and not vigente:
            if entrada is not None and not entrada[1].startswith(MARCA.encode("utf-8")):
                raise ValueError("El índice existente carece de la marca de generación y se conserva intacto.")
            if _leer_trabajo(lector.raiz, INDICE) != entrada:
                raise ValueError("El índice cambió mientras se calculaba su contenido.")
            _escribir_bytes(lector.raiz, INDICE, contenido, exclusivo=entrada is None)
            vigente = True
        salida = (_fallo(operacion, "INDICE_DESACTUALIZADO", INDICE, "El índice falta o requiere regeneración.")
                  if comprobar and not vigente else resultado(operacion))
        salida.update(ruta=INDICE, texto=texto, vigente=vigente, commit=lector.commit)
        return salida
    except (ValueError, OSError, TypeError) as exc:
        return _fallo(operacion, getattr(exc, "codigo", "INDICE_SDD"), getattr(exc, "ruta", INDICE), exc)


def consultar_seccion(raiz, referencia, *, arbol="worktree"):
    """Devuelve únicamente el cuerpo de una sección identificada en un árbol Git."""
    operacion = "seccion-sdd"
    try:
        lector, documentos, _, _ = _vista(raiz, arbol)
        texto = seccion(documentos, referencia)
        errores = validar_grafo(documentos)
        if errores:
            return resultado(operacion, errores)
        salida = resultado(operacion)
        salida.update(referencia=referencia, ruta=REGISTRO + referencia.split("#", 1)[0] + ".md",
                      texto=texto, commit=lector.commit)
        return salida
    except (ValueError, OSError, TypeError) as exc:
        return _fallo(operacion, getattr(exc, "codigo", "SECCION_SDD"), getattr(exc, "ruta", referencia), exc)


def _v2(lector, ruta):
    contenido = lector.leer(ruta)
    try:
        datos, texto = leer(contenido.decode("utf-8"))
    except ValueError as exc:
        raise ValueError(f"Frontmatter V2 inválido en {ruta}: {exc}") from exc
    if type(datos.get("schema")) is not int or datos["schema"] != 1:
        raise ValueError(f"Se requiere frontmatter con schema 1 en {ruta}.")
    procedencia = {"ruta": ruta, "commit": lector.commit, "sha256": hashlib.sha256(contenido).hexdigest()}
    return datos, texto, procedencia


def _marcar_secciones(texto, anclas, ruta):
    if not isinstance(anclas, dict) or not anclas or any(
            not isinstance(titulo, str) or not titulo for titulo in anclas.values()):
        raise ValueError(f"Declara anclas explícitas de sección para {ruta}.")
    lineas = texto.splitlines(keepends=True)
    posiciones = {}
    for identidad, titulo in anclas.items():
        candidatas = [i for i, linea in enumerate(lineas) if linea.rstrip("\r\n") == titulo]
        if len(candidatas) != 1 or candidatas[0] in posiciones:
            raise ValueError(f"El ancla {titulo!r} de {identidad} debe ser única en {ruta}.")
        posiciones[candidatas[0]] = identidad
    salida = []
    for i, linea in enumerate(lineas):
        if i in posiciones:
            salto = "\r\n" if linea.endswith("\r\n") else "\n"
            salida.append(f"<!-- gobernanza:seccion {posiciones[i]} -->{salto}")
        salida.append(linea)
    return list(posiciones[i] for i in sorted(posiciones)), "".join(salida)


def _estado_legado(datos, ruta, traducciones):
    estado = datos.get("estado")
    if not isinstance(estado, str) or estado not in traducciones:
        raise ValueError(f"Estado V2 sin traducción expresa en {ruta}: {estado!r}.")
    return traducciones[estado]


def _especificaciones(lector, specs):
    traducciones = {e: e for e in ("vigente", "borrador", "retirado")}
    for ruta, asignacion in sorted(specs.items()):
        if not isinstance(asignacion, dict) or set(asignacion) != {"ref", "secciones"}:
            raise ValueError(f"Declara ref y secciones para el spec {ruta}.")
        datos, texto, origen = _v2(lector, ruta)
        modulo = datos["id"]
        estado = _estado_legado(datos, ruta, traducciones)
        secciones, marcado = _marcar_secciones(texto, asignacion["secciones"], ruta)
        yield dict(schema=3, tipo="modulo", ref=modulo, estado=estado, procedencia=origen), texto
        yield dict(schema=3, tipo="spec", ref=asignacion["ref"], estado=estado,
                   modulos=[modulo], secciones=secciones, procedencia=origen), marcado


def _funcionalidades(lector, funcionalidades):
    traducciones = {"verificada": "vigente", "vigente": "vigente", "acordada": "vigente",
                    "borrador": "borrador", "propuesta": "borrador", "retirada": "retirado",
                    "retirado": "retirado", "deprecada": "retirado", "cancelada": "retirado"}
    for ruta, asignaciones in sorted(funcionalidades.items()):
        datos, texto, origen = _v2(lector, ruta)
        estado = _estado_legado(datos, ruta, traducciones)
        revisiones = datos["revisiones"]
        if not isinstance(asignaciones, dict) or set(asignaciones) != {str(r) for r in revisiones}:
            raise ValueError(f"Declara las secciones aplicables por cada revisión de {datos['id']} en {ruta}.")
        for revision in revisiones:
            ref = f"{datos['id']}@r{revision}"
            datos_v3 = dict(schema=3, tipo="funcionalidad", ref=ref, estado=estado, modulo=datos["modulo"],
                            criterios=datos["criterios"][str(revision)], secciones=asignaciones[str(revision)],
                            procedencia=origen)
            for campo in ("objetos", "dependencias"):
                if campo in datos:
                    datos_v3[campo] = datos[campo]
            yield datos_v3, texto


def _ruta_legada(ruta, patrones):
    if not isinstance(ruta, str) or not any(re.fullmatch(p, ruta) for p in patrones):
        raise ValueError(f"Fuente V2 no reconocida como contrato, funcionalidad o sesión: {ruta!r}.")


def _sesiones(lector, sesiones):
    traducciones = {e: e for e in ("borrador", "preparacion", "ejecucion", "pendiente_humana",
                                   "lista", "pausada", "bloqueada", "cancelada")}
    traducciones["activa"] = "ejecucion"
    for ruta in sorted(sesiones):
        datos, texto, origen = _v2(lector, ruta)
        estado = _estado_legado(datos, ruta, traducciones)
        resultado_v3 = dict(schema=3, tipo="sesion", ref=datos["id"], estado=estado,
                            funcionalidades=datos["funcionalidades"], procedencia=origen)
        if "plan" in datos:
            resultado_v3["plan"] = datos["plan"]
        inicio = datos.get("inicio", {}).get("registro")
        if inicio is not None and lector.entrada(inicio) is not None:
            resultado_v3["acuerdo"] = inicio
        evidencia = datos.get("evidencia")
        if evidencia is not None and lector.entrada(evidencia) is not None:
            resultado_v3["evidencias"] = [evidencia]
        yield resultado_v3, texto


def plan_migracion(raiz, base, asignaciones, *, sesion=None):
    """Prepara un lote revisable usando mapas explícitos y documentos anclados en Git."""
    operacion = "migracion-sdd"
    try:
        if not isinstance(asignaciones, dict) or set(asignaciones) != {"specs", "funcionalidades", "sesiones"}:
            raise ValueError("El mapa exige specs, funcionalidades y sesiones explícitos.")
        if sesion is not None and (not isinstance(sesion, str) or not re.fullmatch(r"[SG]\d{2}-\d{2}", sesion)):
            raise ValueError(f"Sesión autorizante inválida: {sesion!r}.")
        specs, funciones, sesiones = (asignaciones[c] for c in ("specs", "funcionalidades", "sesiones"))
        if not isinstance(specs, dict) or not isinstance(funciones, dict) or not isinstance(sesiones, list):
            raise ValueError("Declara specs y funcionalidades como mapas y sesiones como lista de rutas.")
        for ruta in specs:
            _ruta_legada(ruta, (r"sdd/spec_[^/]+\.md",))
        for ruta in funciones:
            _ruta_legada(ruta, (r"sdd/funcionalidades/F-\d{4}(?:_[^/]+)?\.md",))
        for ruta in sesiones:
            _ruta_legada(ruta, (r"sesiones/historial/S\d{2}-\d{2}(?:_[^/]+)?\.md",
                                r"gobernanza/sesiones/historial/G\d{2}-\d{2}(?:_[^/]+)?\.md"))
        lector, documentos, _, _ = _vista(raiz, base)
        if lector.commit is None:
            raise ValueError("La migración requiere una referencia Git a un commit fuente.")
        ediciones = []
        for grupo in (_especificaciones(lector, specs), _funcionalidades(lector, funciones), _sesiones(lector, sesiones)):
            for datos, texto in grupo:
                if datos["ref"] in documentos:
                    raise ValueError(f"Ya existe el registro {datos['ref']} en el candidato de migración.")
                documentos[datos["ref"]] = (datos, texto)
                ediciones.append(dict(accion="migrar", datos=datos, texto=texto))
        if not ediciones:
            raise ValueError("El mapa no selecciona registros de migración.")
        errores = validar_grafo(documentos)
        if errores:
            return resultado(operacion, errores)
        salida = resultado(operacion)
        lote = dict(base=lector.commit, cambios=ediciones)
        if sesion is not None:
            lote["sesion"] = sesion
        salida["operacion_sdd"] = lote
        return salida
    except (KeyError, ValueError, OSError, TypeError) as exc:
        return _fallo(operacion, "MIGRACION_SDD", str(base), exc)


def _captura_anclada(raiz, lector, sesion, ruta):
    captura = json_estricto(lector.leer(ruta).decode("utf-8"))
    reconstruida = _capturar(raiz, sesion, captura["ref_acuerdo"], captura["base"])
    if captura != reconstruida:
        raise ValueError(f"La captura {ruta} no corresponde a la autoridad anclada de {sesion}.")
    return dict(sesion=sesion, ruta=ruta, commit=captura["ref_acuerdo"], huella=captura["huella_captura"],
                referencia_pedido=captura["datos"]["acuerdo"]["referencia_pedido"])


def _origen_legado(lector, datos, historico):
    if "procedencia" not in datos:
        return lector, None
    origen = datos["procedencia"]
    fuente = historico(origen["commit"])
    legado, _, comprobada = _v2(fuente, origen["ruta"])
    identidad = datos["ref"].split("@", 1)[0]
    if comprobada != origen or legado.get("id") != identidad:
        raise ValueError(f"La procedencia legada no corresponde a {datos['ref']}.")
    return fuente, legado


def _ficha_traza(lector, datos, historico):
    fuente, origen = _origen_legado(lector, datos, historico)
    if origen is None:
        return datos
    revision = datos["ref"].split("@r", 1)[1]
    evidencias = origen.get("evidencias_por_revision", {}).get(revision, [])
    for ruta in evidencias:
        fuente.leer(ruta)
    return dict(datos, evidencias_legadas=evidencias)


def _pruebas(lector, funcionalidades):
    if lector.entrada("gobernanza/config.json") is None:
        return []
    with materializar(lector.raiz, lector.commit or lector.arbol) as copia:
        repo = cargar(copia.raiz)
    if repo.errores:
        raise ValueError("Inventario de pruebas inconsistente: " + " ".join(e["mensaje"] for e in repo.errores))
    referencias = set()
    for ficha in funcionalidades:
        folio, revision = referencia(ficha["ref"])
        referencias.update(f"{folio}@r{r}" for r in repo.por_id[folio][0].datos["revisiones"] if r <= revision)
    return [p for p in repo.pruebas if p["criterio"].split("/", 1)[0] in referencias]


def _cierre_versionado(lector, version):
    # historial cotejó el recibo, los padres y el árbol sin reinterpretar la
    # evidencia con un runtime posterior al que ejecutó la verificación.
    from .cierre import _padres, _recibo

    integracion = version["commit"]
    seleccionado = LectorArbol(lector.raiz, integracion)
    ruta = version["evidencia"]["ruta"]
    recibo = _recibo(json_estricto(seleccionado.leer(ruta).decode("utf-8")), version["sesion"])
    _, preparada = _padres(lector.raiz, integracion)
    try:
        destinos = _git(lector.raiz, "rev-list", "--first-parent", "--full-history",
                        "refs/heads/main", "--", "sdd/entregas/aplicacion.json").decode("ascii").splitlines()
    except ValueError:
        destinos = []
    cierre = dict(ruta=ruta, commit=preparada, integracion=integracion if integracion in destinos else None)
    return cierre, recibo["informe"]


def _cierre_observado(lector, sesion):
    from .cierre import _creador, _padres, _recibo, confirmar_cierre, evaluar_entrega

    ruta = f"sesiones/estado/{sesion}/cierre.json"
    entrada = lector.entrada(ruta)
    if entrada is None:
        return None, None
    try:
        recibo = _recibo(json_estricto(entrada[1].decode("utf-8")), sesion)
        preparada = _creador(lector.raiz, lector.commit, sesion)
        if _padres(lector.raiz, preparada) != [recibo["fuente_entrada"]]:
            raise ValueError("El recibo no fue guardado sobre el candidato del cierre.")
        historial_cierre = _git(lector.raiz, "rev-list", "--first-parent", "--full-history", lector.commit,
                               "--", ruta).decode("ascii").splitlines()
        for candidato in historial_cierre:
            if _padres(lector.raiz, candidato) != [recibo["base_integracion"], preparada]:
                continue
            confirmado = confirmar_cierre(lector.raiz, sesion, candidato, destino=recibo["destino"], cache=False)
            if confirmado["integracion_confirmada"]:
                return dict(ruta=ruta, commit=preparada, integracion=candidato), recibo["informe"]
        evaluacion = evaluar_entrega(lector.raiz, sesion, recibo["informe"], arbol=preparada,
                                     acuerdo=recibo["acuerdo"], preparacion=recibo.get("preparacion"),
                                     dictamenes=recibo.get("dictamenes", ()))
        if evaluacion["entrega_lista"]:
            return dict(ruta=ruta, commit=preparada, integracion=None), recibo["informe"]
    except (KeyError, TypeError, ValueError, OSError):
        pass  # Un archivo no cotejado no acredita que la sesión esté lista.
    return None, None


def trazar(raiz, sesion, *, arbol="worktree"):
    """Sigue vínculos registrados de una sesión y consulta procedencias conservadas."""
    operacion = "traza-sdd"
    try:
        lector, documentos, operaciones, ancla = _vista(raiz, arbol)
        errores = validar_grafo(documentos)
        if errores:
            return resultado(operacion, errores)
        if sesion not in documentos or documentos[sesion][0]["tipo"] != "sesion":
            raise ValueError(f"La sesión registrada {sesion} no existe en {arbol}.")
        @lru_cache(maxsize=None)
        def historico(commit):
            return LectorArbol(lector.raiz, commit)

        observado = historico(ancla)
        datos, texto = documentos[sesion]
        fichas = [_ficha_traza(lector, documentos[ref][0], historico) for ref in datos.get("funcionalidades", [])]
        fuente, legado = _origen_legado(lector, datos, historico)
        evidencias = list(datos.get("evidencias", []))
        for ruta in evidencias:
            if lector.entrada(ruta) is None:
                fuente.leer(ruta)
        cambios = list(datos.get("cambios", []))
        aprobaciones = []
        ruta_acuerdo = datos.get("acuerdo")
        if ruta_acuerdo is None:
            canonica = f"sesiones/estado/{sesion}/acuerdo.json"
            if observado.entrada(canonica) is not None:
                ruta_acuerdo = canonica
        if ruta_acuerdo is not None:
            legado_registro = legado.get("inicio", {}).get("registro") if legado is not None else None
            origen = fuente if legado_registro == ruta_acuerdo else observado
            aprobaciones.append(_captura_anclada(lector.raiz, origen, sesion, ruta_acuerdo))
        operaciones = [op for op in operaciones
                       if op.get("sesion") == sesion or any(c["ref"] == sesion for c in op["cambios"])]
        for op in operaciones:
            if op.get("aprobacion"):
                aprobaciones.append(dict(op["aprobacion"], operacion_sdd=op["id"]))
            acuerdo = op.get("acuerdo")
            if acuerdo and op.get("sesion"):
                captura = _captura_anclada(lector.raiz, historico(op["base"]), op["sesion"], acuerdo["ruta"])
                aprobaciones.append(dict(captura, operacion_sdd=op["id"]))
        versiones, pruebas_ejecutadas = [], []
        if observado.entrada("sdd/entregas/aplicacion.json") is not None:
            versiones = [v for v in historial(lector.raiz, observado.commit) if v["sesion"] == sesion]
            for version in versiones:
                cambios.extend(c["ruta"] for c in version["cambios"])
        cierre, informe = (_cierre_versionado(observado, versiones[-1])
                           if versiones else _cierre_observado(observado, sesion))
        if cierre is not None:
            evidencias.append(cierre["ruta"])
            pruebas_ejecutadas.append(dict(ruta=cierre["ruta"], commit=cierre["commit"], etapa=informe["etapa"],
                                           huella=informe["huella_informe"],
                                           verificadores=[dict(id=v["id"], exit=v["exit"], resultados=v["resultados"])
                                                          for v in informe["verificadores"]]))
        autoridad_legada = None
        if legado is not None:
            pedido = legado.get("acuerdo", {}).get("referencia_pedido")
            if pedido:
                autoridad_legada = dict(datos["procedencia"], referencia_pedido=pedido,
                                        ejecucion_autorizada=legado.get("ejecucion_autorizada") is True)
        fuente_pruebas = historico(cierre["commit"]) if cierre is not None else observado
        salida = resultado(operacion)
        salida.update(sesion=datos, texto=texto, funcionalidades=fichas, cambios=unicos(cambios),
                      evidencias=unicos(evidencias), aprobaciones=unicos(aprobaciones), operaciones=operaciones,
                      autoridad_legada=autoridad_legada, cierre=cierre, entrega_lista=cierre is not None,
                      integracion_confirmada=cierre is not None and cierre["integracion"] is not None,
                      versiones=versiones, pruebas_ejecutadas=pruebas_ejecutadas,
                      pruebas_declaradas=_pruebas(fuente_pruebas, fichas), commit=lector.commit)
        return salida
    except (KeyError, ValueError, OSError, TypeError) as exc:
        return _fallo(operacion, getattr(exc, "codigo", "TRAZA_SDD"), getattr(exc, "ruta", sesion), exc)
