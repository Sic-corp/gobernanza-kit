"""Registro de las versiones integradas de la solución (F-0111)."""

import re

from .acuerdos import _hash
from .arboles import LectorArbol, _git, commit_lectura, materializar
from .documentos import cargar, json_estricto
from .modelo import coincide, referencia


MANIFIESTO = "sdd/entregas/aplicacion.json"
_CONFIG = "gobernanza/config.json"
_BASE = "V1.00"
_INACTIVAS = {"borrador", "propuesta", "retirada", "retirado", "deprecada", "cancelada"}


def _version(texto):
    partes = re.fullmatch(r"V([1-9]\d*)\.(\d{2,})", texto) if isinstance(texto, str) else None
    if not partes or partes[2] != f"{int(partes[2]):02d}":
        raise ValueError(f"Versión de aplicación inválida: {texto!r}.")
    return int(partes[1]), int(partes[2])


def _siguiente(anterior, tipo):
    serie, incremento = _version(anterior)
    return f"V{serie + 1}.00" if tipo == "estable" else f"V{serie}.{incremento + 1:02d}"


def _json_en(arbol, ruta):
    datos = json_estricto(arbol.leer(ruta).decode("utf-8"))
    if not isinstance(datos, dict):
        raise ValueError(f"Se requiere un objeto en {ruta}.")
    return datos


def _repositorio(raiz, commit):
    with materializar(raiz, commit) as copia:
        repo = cargar(copia.raiz)
    if repo.errores:
        primera = repo.errores[0]
        raise ValueError(f"Contratos de {commit} inválidos: {primera['ruta']}: {primera['mensaje']}")
    return repo


def _activas(repo):
    return {d.id: d for d in repo.documentos
            if d.tipo == "funcionalidad" and d.datos.get("estado") not in _INACTIVAS}


def _ref_funcionalidad(ref):
    partes = referencia(ref)
    if partes is None or not partes[0].startswith("F-") or partes[1] is None:
        raise ValueError(f"Se requiere una funcionalidad con revisión: {ref!r}.")
    return partes


def _refs(valores):
    if not isinstance(valores, list) or not valores:
        raise ValueError("Se requieren funcionalidades con revisiones explícitas.")
    seleccion = dict(_ref_funcionalidad(ref) for ref in valores)
    if len(seleccion) != len(valores):
        raise ValueError("Cada funcionalidad requiere una sola revisión en la entrega o la meta.")
    return seleccion


def _evidencia(informe, sesion):
    if (not isinstance(informe, dict) or type(informe.get("schema")) is not int or informe["schema"] != 1
            or informe.get("sesion") != sesion or informe.get("etapa") != "entrega"
            or type(informe.get("codigo")) is not int or informe["codigo"] != 0
            or informe.get("pruebas_aprobadas") is not True):
        raise ValueError("La versión requiere evidencia verde de entrega para su sesión.")
    huellas = {k: informe.get(k) for k in ("huella_informe", "huella_entradas")}
    if (any(not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None for v in huellas.values())
            or _hash({k: v for k, v in informe.items() if k != "huella_informe"}) != huellas["huella_informe"]):
        raise ValueError("La evidencia de entrega de la versión tiene una huella inválida.")
    return dict(ruta=f"sesiones/estado/{sesion}/cierre.json", **huellas)


def _padres(raiz, commit):
    return _git(raiz, "rev-list", "-n", "1", "--parents", commit).decode("ascii").split()[1:]


def _comprobar_recibo(raiz, arbol, registro, padres):
    sesion = registro.get("sesion")
    if (not isinstance(sesion, str) or re.fullmatch(r"[SG]\d{2}-\d{2}", sesion) is None
            or len(padres) != 2 or registro.get("base_integracion") != padres[0]):
        raise ValueError("El manifiesto de versión requiere un cierre integrado con dos padres exactos.")
    recibo = _json_en(arbol, f"sesiones/estado/{sesion}/cierre.json")
    evidencia = _evidencia(recibo.get("informe"), sesion)
    cierre = {k: v for k, v in recibo.items() if k != "huella_cierre"}
    if (recibo.get("version_aplicacion") != registro or recibo.get("sesion") != sesion
            or recibo.get("base_integracion") != padres[0] or recibo.get("destino") != "refs/heads/main"
            or recibo.get("huella_cierre") != _hash(cierre)
            or _padres(raiz, padres[1]) != [recibo.get("fuente_entrada")]
            or registro.get("evidencia") != evidencia
            or any(recibo.get(k) != evidencia[k] for k in ("huella_entradas", "huella_informe"))
            or recibo.get("acuerdo", {}).get("datos", {}).get("acuerdo", {}).get("integracion_local") is not True
            or _git(raiz, "rev-parse", arbol.commit + "^{tree}") != _git(raiz, "rev-parse", padres[1] + "^{tree}")):
        raise ValueError("El manifiesto de versión difiere del recibo o del árbol del cierre.")


def _linea_base(raiz, commit):
    repo = _repositorio(raiz, commit)
    return dict(schema=1, version=_BASE, anterior=None, tipo="linea_base", commit=commit,
                base_integracion=None, sesion=None, evidencia=None, cambios=[],
                funcionalidades=sorted(d.ref() for d in _activas(repo).values()))


def historial(raiz, destino="main"):
    """Devuelve la cadena cronológica cotejada en el primer padre de la ref."""
    if destino == "main":
        destino = "refs/heads/main"
    punta = commit_lectura(raiz, destino)
    commits = _git(raiz, "rev-list", "--first-parent", "--full-history", "--reverse",
                   punta, "--", MANIFIESTO).decode("ascii").split()
    versiones = []
    ultima_entrada = None
    for commit in commits:
        arbol = LectorArbol(raiz, commit)
        entrada = arbol.entradas.get(MANIFIESTO)
        if entrada == ultima_entrada:
            continue
        if entrada is None:
            raise ValueError("El manifiesto de versión fue retirado de la historia de integración.")
        registro = _json_en(arbol, MANIFIESTO)
        padres = _padres(raiz, commit)
        _comprobar_recibo(raiz, arbol, registro, padres)
        if not versiones:
            versiones.append(_linea_base(raiz, padres[0]))
        anterior = versiones[-1]["version"]
        tipo = registro.get("tipo")
        if (type(registro.get("schema")) is not int or registro["schema"] != 1
                or tipo not in {"entrega", "estable"} or registro.get("anterior") != anterior
                or registro.get("version") != _siguiente(anterior, tipo)
                or (len(versiones) == 1 and tipo != "entrega")):
            raise ValueError("La secuencia del manifiesto de aplicación es inválida.")
        versiones.append(dict(registro, commit=commit))
        ultima_entrada = entrada
    return versiones


def _integradas(versiones):
    revisiones = {}
    for entrada in versiones:
        revisiones.update(_ref_funcionalidad(ref) for ref in entrada["funcionalidades"])
    return revisiones


def _estado_config(arbol):
    config = _json_en(arbol, _CONFIG)
    activa = config.get("versionado_aplicacion", False)
    if type(activa) is not bool:
        raise ValueError("versionado_aplicacion requiere un valor booleano.")
    return config, activa


def _es_solucion(ruta, config):
    raices = config["raices"]
    return (any(coincide(ruta, patron) for patron in raices["solucion"])
            and not any(coincide(ruta, patron) for patron in raices["pruebas"]))


def _rutas_solucion(antes, despues, config_antes, config_despues):
    return [ruta for ruta in sorted(antes.rutas | despues.rutas)
            if antes.entradas.get(ruta) != despues.entradas.get(ruta)
            and ((ruta in antes.rutas and _es_solucion(ruta, config_antes))
                 or (ruta in despues.rutas and _es_solucion(ruta, config_despues)))]


def comprobar_vigencia(raiz, ultima, base):
    """Comprueba que el primer padre entre la última versión y la punta solo cambia gestión."""
    sucesores = _git(raiz, "rev-list", "--first-parent", "--reverse", ultima + ".." + base).decode("ascii").split()
    anterior = LectorArbol(raiz, ultima)
    config_anterior, _ = _estado_config(anterior)
    for commit in sucesores:
        actual = LectorArbol(raiz, commit)
        config_actual, _ = _estado_config(actual)
        if _rutas_solucion(anterior, actual, config_anterior, config_actual):
            raise ValueError(f"La base incluye cambios de solución sin versión integrada en {commit}.")
        anterior, config_anterior = actual, config_actual


def _describir_objeto(repo, ruta, activas):
    duenos = {}
    for doc in repo.documentos:
        if doc.id in activas and any(coincide(ruta, patron) for patron in doc.datos.get("objetos", [])):
            duenos[doc.id] = (doc.datos["modulo"], {doc.ref()})
        if doc.tipo != "modulo":
            continue
        for objeto in doc.datos.get("objetos_compartidos", []):
            if coincide(ruta, objeto["ruta"]):
                refs = duenos.setdefault(doc.id, (doc.id, set()))[1]
                for ref in objeto["consumidores"]:
                    identidad, revision = referencia(ref)
                    ficha = activas.get(identidad)
                    if ficha is not None and (revision is None or ficha.ref() == ref):
                        refs.add(ficha.ref())
    if len(duenos) > 1:
        raise ValueError(f"El objeto de solución {ruta} tiene más de un propietario declarado.")
    propietario = next(iter(duenos), None)
    modulo, refs = duenos.get(propietario, (None, set()))
    return propietario, modulo, refs


def _atribuir(rutas, antes, despues, repo_base, repo_fuente, autorizadas):
    cambios, participan = [], set()
    activas_base, activas_fuente = _activas(repo_base), _activas(repo_fuente)
    for ruta in rutas:
        antigua, nueva = ruta in antes.rutas, ruta in despues.rutas
        propietario_anterior, _, refs_anteriores = (
            _describir_objeto(repo_base, ruta, activas_base) if antigua else (None, None, set()))
        repo, activas = (repo_fuente, activas_fuente) if nueva else (repo_base, activas_base)
        propietario, modulo, refs = _describir_objeto(repo, ruta, activas)
        if propietario is None:
            raise ValueError(f"El objeto de solución {ruta} requiere un propietario declarado.")
        participantes = {referencia(ref)[0] for ref in refs} & autorizadas.keys()
        if not participantes:
            raise ValueError(f"El objeto {ruta} carece de una F propietaria o consumidora autorizada.")
        accion = "modificacion" if antigua and nueva else "alta" if nueva else "baja"
        cambio = dict(ruta=ruta, accion=accion, modulo=modulo, funcionalidades=sorted(refs))
        if propietario_anterior is not None and propietario_anterior != propietario:
            anteriores_autorizadas = {referencia(ref)[0] for ref in refs_anteriores} & autorizadas.keys()
            if not anteriores_autorizadas:
                raise ValueError(f"La transferencia de {ruta} requiere el alcance del propietario anterior {propietario_anterior}.")
            participantes.update(anteriores_autorizadas)
            cambio.update(propietario_anterior=propietario_anterior, funcionalidades_anteriores=sorted(refs_anteriores))
        participan.update(participantes)
        cambios.append(cambio)
    entregadas = {}
    for identidad in sorted(participan):
        doc = activas_fuente.get(identidad)
        if doc is None or doc.datos["revision_actual"] != autorizadas[identidad]:
            raise ValueError(f"La revisión autorizada de {identidad} debe ser la vigente del candidato.")
        entregadas[identidad] = doc
    return cambios, entregadas


def _criterios(repositorio, revisiones):
    fichas = _activas(repositorio)
    return {c["referencia"] for identidad, revision in revisiones.items()
            for c in fichas[identidad].criterios(revision)}


def _comprobar_pruebas(repo, criterios, informe):
    verdes = {(verificador.get("id"), r["selector"])
              for verificador in informe.get("verificadores", [])
              if verificador.get("exit") == 0 and verificador.get("completa") is True
              for r in verificador.get("resultados", [])
              if r.get("estado") == "aprobado" and r.get("selector") in verificador.get("casos_ejecutados", [])}
    vinculadas = {criterio: set() for criterio in criterios}
    for prueba in repo.pruebas:
        if prueba["criterio"] in vinculadas:
            vinculadas[prueba["criterio"]].add((prueba["verificador"], prueba["selector"]))
    faltan = sorted(c for c, casos in vinculadas.items() if not casos or casos - verdes)
    if not criterios or faltan:
        raise ValueError("Falta prueba vinculada y aprobada para la versión: " + ", ".join(faltan))


def _corte(meta, anterior, integradas, repo, informe, acuerdo):
    serie, _ = _version(anterior)
    if (type(meta.get("serie")) is not int or meta["serie"] != serie + 1
            or not isinstance(meta.get("objetivo"), str) or not meta["objetivo"].strip()):
        raise ValueError("La meta debe definir el objetivo y la siguiente serie estable.")
    if (acuerdo.get("integracion_local") is not True
            or not isinstance(meta.get("autorizacion"), str) or not meta["autorizacion"].strip()):
        raise ValueError("El corte estable requiere autorización explícita para esa meta.")
    minimas = _refs(meta.get("requisitos"))
    autorizadas = _refs(acuerdo.get("funcionalidades"))
    activas = _activas(repo)
    for identidad, revision in minimas.items():
        registrada = integradas.get(identidad, 0)
        doc = activas.get(identidad)
        if revision > registrada or doc is None or doc.datos["revision_actual"] != registrada:
            raise ValueError(f"La funcionalidad {identidad}@r{revision} requerida no está integrada en el corte.")
        if autorizadas.get(identidad) != registrada:
            raise ValueError(f"El acuerdo del corte debe incluir la revisión integrada {doc.ref()}.")
    permitidos = {c["referencia"] for f in minimas
                  for n in range(1, integradas[f] + 1) for c in activas[f].criterios(n)}
    criterios = meta.get("criterios", sorted(permitidos))
    if (not isinstance(criterios, list) or not criterios
            or any(not isinstance(c, str) or c not in permitidos for c in criterios)):
        raise ValueError("Los criterios del corte deben corresponder a las F integradas de su meta.")
    _comprobar_pruebas(repo, permitidos, informe)
    return dict(objetivo=meta["objetivo"], requisitos=sorted(meta["requisitos"]), criterios=sorted(set(criterios)),
                autorizacion=meta["autorizacion"])


def preparar_version(raiz, base, fuente, acuerdo, informe):
    """Calcula el registro para el mismo candidato que prepara el cierre."""
    antes, despues = LectorArbol(raiz, base), LectorArbol(raiz, fuente)
    config_fuente, activa_fuente = _estado_config(despues)
    promesa = acuerdo["datos"]["acuerdo"]
    meta = promesa.get("version_aplicacion", {})
    if not isinstance(meta, dict) or meta.get("tipo", "entrega") not in {"entrega", "estable"}:
        raise ValueError("version_aplicacion debe declarar el tipo entrega o estable.")
    if not activa_fuente:
        ya_activa = _CONFIG in antes.rutas and _estado_config(antes)[1]
        if ya_activa or meta:
            raise ValueError("La sesión no puede omitir el versionado de aplicación acordado.")
        return None
    config_base, _ = _estado_config(antes)
    if antes.entradas.get(MANIFIESTO) != despues.entradas.get(MANIFIESTO):
        raise ValueError(f"Solo el cierre puede generar el manifiesto de versión en {MANIFIESTO}.")
    versiones = historial(raiz, antes.commit)
    if versiones and versiones[-1]["commit"] != antes.commit:
        comprobar_vigencia(raiz, versiones[-1]["commit"], antes.commit)
    rutas = _rutas_solucion(antes, despues, config_base, config_fuente)
    tipo = meta.get("tipo", "entrega")
    if tipo == "entrega" and not rutas:
        return None
    if tipo == "estable" and (rutas or not versiones):
        raise ValueError("El corte estable requiere una versión previa y una sesión sin cambios de solución.")
    if not versiones:
        versiones = [_linea_base(raiz, antes.commit)]
    anterior = versiones[-1]["version"]
    integradas = _integradas(versiones)
    sesion = acuerdo["sesion"]
    if not isinstance(sesion, str) or re.fullmatch(r"[SG]\d{2}-\d{2}", sesion) is None:
        raise ValueError("El manifiesto de versión requiere una sesión S/G.")
    evidencia = _evidencia(informe, sesion)
    repo_fuente = _repositorio(raiz, despues.commit)
    registro = dict(schema=1, version=_siguiente(anterior, tipo), anterior=anterior, tipo=tipo, sesion=sesion,
                    base_integracion=antes.commit, evidencia=evidencia, funcionalidades=[], cambios=[])
    if tipo == "estable":
        registro["meta"] = _corte(meta, anterior, integradas, repo_fuente, informe, promesa)
        return registro
    repo_base = _repositorio(raiz, antes.commit)
    registro["cambios"], entregadas = _atribuir(rutas, antes, despues, repo_base, repo_fuente, _refs(promesa["funcionalidades"]))
    for identidad, doc in entregadas.items():
        previa = integradas.get(identidad, 0)
        if doc.datos["revision_actual"] not in {previa, previa + 1}:
            raise ValueError(f"{doc.ref()} debe seguir la última revisión integrada de {identidad}.")
    revisiones = {f: d.datos["revision_actual"] for f, d in entregadas.items()}
    _comprobar_pruebas(repo_fuente, _criterios(repo_fuente, revisiones), informe)
    registro["funcionalidades"] = sorted(d.ref() for d in entregadas.values())
    if "origen" in meta or "referencia_origen" in meta:
        if (meta.get("origen") not in {v["version"] for v in versiones}
                or not isinstance(meta.get("referencia_origen"), str) or not meta["referencia_origen"].strip()):
            raise ValueError("La corrección requiere versión integrada de origen y referencia de evidencia.")
        registro.update(origen=meta["origen"], referencia_origen=meta["referencia_origen"])
    return registro
