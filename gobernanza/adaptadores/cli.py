"""Traducción de argumentos a APIs del núcleo; F-0108@r1."""

import argparse
import json
import os
import re
import stat
from pathlib import Path
import sys

from . import ruta
from ..nucleo.acuerdos import capturar_acuerdo, validar_cambios
from ..nucleo.arboles import materializar
from ..nucleo.cierre import confirmar_cierre, evaluar_entrega, preparar_cierre
from ..nucleo.contexto import contexto
from ..nucleo.convivencia import informe_error, ErrorConvivencia, seleccionar_perfil
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import conciliar_guardado, iniciar, leer_inicio, planificar_guardado, publicar_informe
from ..nucleo.validacion import validar
from ..nucleo.verificacion import verificar
from ..nucleo.modelo import diagnostico, referencia, resultado
from ..nucleo.servicio_sdd import solicitar_sdd


class UsoInvalido(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsoInvalido(message)


def _comunes(parser):
    parser.add_argument("--raiz", default=argparse.SUPPRESS, help="Raíz del consumidor (directorio actual por defecto)")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Salida JSON estructurada")


def _archivos(parser, *, informe=False):
    parser.add_argument("--acuerdo", help="Snapshot JSON; si se omite se usa el inicio guardado o se captura HEAD")
    parser.add_argument("--base", help="Base Git explícita al capturar el acuerdo")
    parser.add_argument("--preparacion", help="Informe JSON de preparación")
    parser.add_argument("--dictamenes", help="Dictamen JSON concreto o lista")
    if informe:
        parser.add_argument("--informe", help="Informe JSON de entrega")


def _parser():
    parser = Parser(prog="python3 -m gobernanza", description="Kit local: contratos, pruebas y guardados recuperables.")
    _comunes(parser)
    verbos = parser.add_subparsers(dest="verbo", required=True, parser_class=Parser)
    p = verbos.add_parser("contexto", help="Consultar contratos y pruebas relacionados")
    _comunes(p)
    selector = p.add_mutually_exclusive_group()
    selector.add_argument("--sesion")
    selector.add_argument("--funcionalidad")
    selector.add_argument("--ruta")
    ancla = p.add_mutually_exclusive_group()
    ancla.add_argument("--arbol", default="worktree", help="Árbol de trabajo, índice o ancla histórica Git")
    ancla.add_argument("--integrada", action="store_true", help="Consulta la revisión integrada vigente de --funcionalidad")
    ancla.add_argument("--version", help="Versión integrada V1.00, con --funcionalidad o --ruta opcionales")
    p = verbos.add_parser("validar", help="Validar sin ejecutar pruebas")
    _comunes(p)
    p.add_argument("--sesion")
    p.add_argument("--arbol", help="worktree, staged o referencia Git literal")
    p.add_argument("--modo", choices=["borrador", "trabajo", "entrega"], default="borrador")
    p.add_argument("--fase", choices=["preparacion", "ejecucion"], default="preparacion")
    _archivos(p, informe=True)
    p.add_argument("--entrada-nativa", help="Referencias JSON a las fuentes y registros nativos")
    guardado = p.add_mutually_exclusive_group()
    guardado.add_argument("--planificar-guardado", action="store_true", help="Propone el lote nativo desde el índice")
    guardado.add_argument("--plan-guardado", help="Lote JSON de inicio, ejecución o cierre para cotejar")
    p = verbos.add_parser("iniciar", help="Fijar acuerdo y guardado documental idempotente")
    _comunes(p)
    p.add_argument("--sesion", required=True)
    p.add_argument("--base")
    p.add_argument("--entrada-nativa", help="Referencias JSON del acuerdo y propuesta nativos")
    p = verbos.add_parser("verificar", help="Ejecutar unittest en copia materializada y publicar informe")
    _comunes(p)
    p.add_argument("--sesion", required=True)
    p.add_argument("--arbol", default="staged")
    p.add_argument("--etapa", choices=["preparacion", "entrega"], required=True)
    p.add_argument("--esperados-rojos", help="JSON selector → motivo")
    p.add_argument("--salida", help="Ruta de publicación dentro de salidas declaradas")
    p.add_argument("--timeout", type=float, default=30)
    _archivos(p)
    p.add_argument("--entrada-nativa", help="Referencias JSON de preparación y acuerdos nativos")
    p = verbos.add_parser("cerrar", help="Preparar cierre o confirmar integración ya realizada")
    _comunes(p)
    p.add_argument("--sesion", required=True)
    accion = p.add_mutually_exclusive_group(required=True)
    accion.add_argument("--preparar", action="store_true")
    accion.add_argument("--confirmar", action="store_true")
    p.add_argument("--integracion", help="SHA del merge --no-ff ya realizado")
    p.add_argument("--destino", default="main")
    p.add_argument("--cierre", help="Manifiesto JSON; si se omite se lee el registro canónico")
    p.add_argument("--sin-cache", action="store_true")
    _archivos(p, informe=True)
    p.add_argument("--entrada-nativa", help="Referencias JSON de integración y cierre nativos")
    sdd = verbos.add_parser("sdd", help="Registrar y consultar contratos tipados")
    _comunes(sdd)
    operaciones = sdd.add_subparsers(dest="accion_sdd", required=True)
    for nombre in ("registrar", "migrar", "indice", "seccion", "traza", "estado", "servir", "aceptar-candidato"):
        op = operaciones.add_parser(nombre)
        _comunes(op)
        if nombre in {"registrar", "migrar"}:
            op.add_argument("--aplicar", action="store_true", help="Guardar el lote simulado")
        if nombre in {"indice", "seccion", "traza"}:
            op.add_argument("--arbol", default="worktree")
        if nombre in {"registrar", "estado", "indice"}:
            op.add_argument("--socket", type=Path, help="Socket del escritor local de SDD")
        if nombre in {"servir", "aceptar-candidato"}:
            op.add_argument("--config", required=True, type=Path, help="Configuración privada del escritor")
        if nombre == "aceptar-candidato":
            op.add_argument("--candidato", required=True, help="SHA completo importado al repositorio de autoridad")
        if nombre == "registrar":
            op.add_argument("--entrada", required=True, help="Archivo JSON con el lote de cambios")
        if nombre == "migrar":
            op.add_argument("--base", required=True)
            op.add_argument("--asignaciones", required=True)
            op.add_argument("--sesion", required=True)
        if nombre == "seccion":
            op.add_argument("--ref", required=True)
        if nombre == "traza":
            op.add_argument("--sesion", required=True)
        if nombre == "indice":
            modo = op.add_mutually_exclusive_group()
            modo.add_argument("--comprobar", action="store_true")
            modo.add_argument("--escribir", action="store_true")
    ruta.opciones(verbos, _comunes)
    return parser


def _leer(raiz, nombre, defecto=None, *, informe=False):
    if nombre is None:
        return defecto
    ruta = Path(nombre)
    if not ruta.is_absolute():
        ruta = raiz / ruta
    datos = json_estricto(ruta.read_text(encoding="utf-8"))
    if informe and isinstance(datos, dict) and isinstance(datos.get("informe"), dict):
        datos = datos["informe"]
    return datos


def _dictamenes(raiz, nombre):
    datos = _leer(raiz, nombre, [])
    if isinstance(datos, dict):
        return datos.get("dictamenes", [datos])
    return datos


def _acuerdo(raiz, args):
    if args.acuerdo is not None:
        return _leer(raiz, args.acuerdo)
    sesion = args.sesion
    if referencia(sesion) == (sesion, None) and sesion.startswith(("S", "G")):
        registro = raiz / "sesiones/estado" / sesion / "acuerdo.json"
        if registro.exists() or registro.is_symlink():
            return leer_inicio(raiz, sesion)
    return capturar_acuerdo(raiz, sesion, base=args.base)


def _renombrar(salida, operacion, **datos):
    return dict(salida, operacion=operacion, **datos)


def _sdd(raiz, args):
    from ..nucleo.navegacion_sdd import consultar_seccion, generar_indice, plan_migracion, trazar
    from ..nucleo.registro_sdd import registrar

    accion = args.accion_sdd
    if accion in {"servir", "aceptar-candidato"}:
        if accion == "aceptar-candidato" and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", args.candidato) is None:
            raise UsoInvalido("El candidato requiere un SHA Git completo y literal.")
        return _administrar_sdd(args)
    socket = getattr(args, "socket", None) or os.environ.get("GOBERNANZA_SDD_SOCKET")
    if accion == "estado":
        return _solicitud_sdd(raiz, socket, "estado")
    if accion == "registrar":
        lote = _leer(raiz, args.entrada)
        if socket or "generacion" in lote:
            return _solicitud_sdd(raiz, socket, "registrar", aplicar=args.aplicar, lote=lote)
        return registrar(raiz, lote, aplicar=args.aplicar)
    if accion == "indice" and socket:
        if args.arbol != "worktree":
            raise UsoInvalido("El escritor opera solamente sobre el worktree registrado.")
        estado = _solicitud_sdd(raiz, socket, "estado")
        if estado["codigo"]:
            return estado
        lote = {"base": estado["base"], "generacion": estado["generacion"],
                "cambios": [{"accion": "indice"}]}
        salida = _solicitud_sdd(raiz, socket, "registrar", aplicar=args.escribir, lote=lote)
        if args.comprobar and not salida["codigo"] and salida["cambios"]:
            return resultado("indice", [diagnostico(
                "SDD_INDICE_DESACTUALIZADO", "sdd/INDICE.md", "Índice nativo vigente",
                "La proyección del índice ha cambiado.", "Regenera el índice mediante sdd indice --escribir."
            )])
        return salida
    if accion == "migrar":
        plan = plan_migracion(raiz, args.base, _leer(raiz, args.asignaciones), sesion=args.sesion)
        if plan["codigo"] or not args.aplicar:
            return plan
        return registrar(raiz, plan["operacion_sdd"], aplicar=True)
    if accion == "seccion":
        return consultar_seccion(raiz, args.ref, arbol=args.arbol)
    if accion == "traza":
        return trazar(raiz, args.sesion, arbol=args.arbol)
    return generar_indice(raiz, comprobar=args.comprobar, escribir=args.escribir, arbol=args.arbol)


def _solicitud_sdd(raiz, socket, operacion, **datos):
    if not socket:
        raise UsoInvalido("Indica --socket o GOBERNANZA_SDD_SOCKET para contactar al escritor de SDD.")
    try:
        respuesta = solicitar_sdd(Path(socket), dict(datos, operacion=operacion, raiz=str(raiz)))
        if not isinstance(respuesta, dict) or type(respuesta.get("codigo")) is not int:
            raise ValueError("Respuesta inválida del escritor de SDD.")
    except (OSError, ValueError) as exc:
        respuesta = {"codigo": 1, "resumen": str(exc)}
    errores = []
    if respuesta["codigo"]:
        errores.append(diagnostico(
            "SDD_SERVICIO", str(socket), "Operación válida del escritor de SDD",
            respuesta.get("resumen", "Solicitud rechazada."), "Corrige el diagnóstico y vuelve a solicitar la operación."
        ))
    salida = resultado(operacion, errores, codigo=respuesta["codigo"])
    for campo in ("resumen", "raiz", "base", "generacion", "archivos", "cambios", "recibo", "idempotente"):
        if campo in respuesta:
            salida[campo] = respuesta[campo]
    return salida


def _administrar_sdd(args):
    from ..nucleo.proteccion_sdd import (
        aceptar_candidato_sdd, capturar_imagen_sdd, verificar_almacen_sdd,
        verificar_autoridad_git, verificar_permisos_sdd,
    )
    from ..nucleo.sdd_heimdall import planificar_heimdall
    from ..nucleo.servicio_sdd import ConfiguracionSDD, ServicioSDD

    ruta = args.config
    datos_archivo = ruta.lstat()
    if (not ruta.is_absolute() or ruta != ruta.resolve(strict=True)
            or not stat.S_ISREG(datos_archivo.st_mode) or datos_archivo.st_uid != os.geteuid()
            or datos_archivo.st_mode & 0o077):
        raise ValueError("La configuración debe ser un archivo privado absoluto del escritor.")
    datos = _leer(ruta.parent, ruta)
    campos = {"raiz", "estado", "socket", "uid_agente", "gid_agente", "base", "alcance",
              "referencia", "repositorio_git"}
    if datos.keys() != campos or not isinstance(datos["alcance"], list):
        raise ValueError("Configuración inválida del escritor de SDD.")
    config = ConfiguracionSDD(
        raiz=Path(datos["raiz"]), estado=Path(datos["estado"]), socket=Path(datos["socket"]),
        uid_agente=datos["uid_agente"], gid_agente=datos["gid_agente"], base=datos["base"],
        alcance=tuple(datos["alcance"]), referencia=Path(datos["referencia"]),
    )
    if ruta.is_relative_to(config.raiz):
        raise ValueError("La configuración debe vivir fuera del checkout del agente.")

    verificar_almacen_sdd(ruta, uid_agente=config.uid_agente, privado=True)
    repositorio = Path(datos["repositorio_git"])
    verificar_autoridad_git(repositorio, raiz_agente=config.raiz, uid_agente=config.uid_agente)

    def comprobar(raiz, uid_agente):
        verificar_permisos_sdd(raiz, uid_agente=uid_agente)
        for almacen in (ruta, config.estado, config.referencia.parent):
            verificar_almacen_sdd(almacen, uid_agente=uid_agente, privado=True)
        for almacen in (config.referencia, config.socket.parent):
            verificar_almacen_sdd(almacen, uid_agente=uid_agente, privado=False)

    imagen_base = capturar_imagen_sdd(repositorio, config.base)
    servicio = ServicioSDD(
        config, planificar_heimdall, comprobar_proteccion=comprobar, imagen_base=imagen_base
    )
    if args.accion_sdd == "servir":
        servicio.servir()
        return resultado("servir")

    def aceptar(imagen):
        verificar_autoridad_git(repositorio, raiz_agente=config.raiz, uid_agente=config.uid_agente)
        with materializar(repositorio, args.candidato) as candidato:
            if planificar_heimdall(candidato.raiz, [{"accion": "indice"}],
                                   autorizar=lambda *_: None):
                raise ValueError("El índice de SDD está desactualizado para las fuentes del candidato.")
        return aceptar_candidato_sdd(repositorio, args.candidato, imagen, base=config.base)

    return dict(resultado("aceptar-candidato"), commit=servicio.con_imagen_vigente(aceptar))


def _despachar(args):
    raiz = Path(getattr(args, "raiz", ".")).resolve()
    if args.verbo == "ruta":
        return ruta.despachar(raiz, args, _leer)
    if args.verbo == "tablero":
        from ..tablero.__main__ import main as abrir
        opciones = ["--raiz", str(raiz), "--puerto", str(args.puerto)]
        if args.sin_abrir:
            opciones.append("--sin-abrir")
        return dict(resultado("tablero", codigo=abrir(opciones)), _ayuda=True)
    if args.verbo == "sdd":
        return _sdd(raiz, args)
    if args.verbo == "contexto":
        historico = args.arbol not in {"HEAD", "worktree", "staged"}
        return contexto(raiz, sesion=args.sesion, funcionalidad=args.funcionalidad, ruta=args.ruta,
                        arbol=args.arbol, historico=historico, integrada=args.integrada, version=args.version)
    if args.verbo == "validar" and args.arbol is None:
        args.arbol = "staged" if args.planificar_guardado else "worktree"
    requiere_nativo = bool(getattr(args, "entrada_nativa", None) is not None
                           or getattr(args, "planificar_guardado", False)
                           or getattr(args, "plan_guardado", None) is not None)
    repo = seleccionar_perfil(raiz, getattr(args, "arbol", "HEAD"), requiere_nativo=requiere_nativo)
    if repo is not None:
        return _despachar_nativo(repo, args)
    if args.verbo == "iniciar":
        ruta.completar_raices_de_inicio(raiz, args.base)
        return iniciar(raiz, args.sesion, base=args.base)
    if args.verbo == "validar":
        if args.modo != "borrador" and not args.sesion:
            raise UsoInvalido("--sesion es obligatorio para validar trabajo o entrega")
        if args.modo == "entrega" and not args.informe:
            raise UsoInvalido("--informe es obligatorio para validar entrega")
        if args.modo == "entrega":
            salida = evaluar_entrega(raiz, args.sesion, _leer(raiz, args.informe, informe=True),
                                    arbol=args.arbol, acuerdo=_acuerdo(raiz, args),
                                    preparacion=_leer(raiz, args.preparacion, informe=True),
                                    dictamenes=_dictamenes(raiz, args.dictamenes))
        else:
            salida = validar(raiz, arbol=args.arbol)
            if salida["codigo"] == 0 and args.modo == "trabajo":
                salida = validar_cambios(raiz, args.sesion, _acuerdo(raiz, args), arbol=args.arbol,
                                         fase=args.fase, preparacion=_leer(raiz, args.preparacion, informe=True),
                                         dictamenes=_dictamenes(raiz, args.dictamenes))
        return _renombrar(salida, "validar", modo=args.modo, arbol=args.arbol)
    if args.verbo == "verificar":
        informe = verificar(raiz, args.sesion, arbol=args.arbol, etapa=args.etapa, acuerdo=_acuerdo(raiz, args),
                            preparacion=_leer(raiz, args.preparacion, informe=True),
                            dictamenes=_dictamenes(raiz, args.dictamenes),
                            esperados_rojos=_leer(raiz, args.esperados_rojos, {}), timeout=args.timeout)
        publicacion = publicar_informe(raiz, args.sesion, informe, destino=args.salida)
        errores = list(informe["errores"]) + list(publicacion["errores"])
        codigo = informe["codigo"] or publicacion["codigo"]
        salida = resultado("verificar", errores, codigo=codigo)
        salida.update(informe=informe, ruta_informe=publicacion.get("ruta_informe"),
                      limites=dict(informe["limites"]),
                      resumen=informe["resumen"] if not publicacion["codigo"] else publicacion["resumen"])
        return salida
    if args.verbo == "cerrar":
        if args.preparar:
            if not args.informe:
                raise UsoInvalido("--informe es obligatorio para cerrar --preparar")
            salida = preparar_cierre(raiz, args.sesion, _leer(raiz, args.informe, informe=True),
                                     destino=args.destino, acuerdo=_acuerdo(raiz, args),
                                     preparacion=_leer(raiz, args.preparacion, informe=True),
                                     dictamenes=_dictamenes(raiz, args.dictamenes))
        else:
            if not args.integracion:
                raise UsoInvalido("--integracion es obligatorio para cerrar --confirmar")
            salida = confirmar_cierre(raiz, args.sesion, args.integracion,
                                      cierre=_leer(raiz, args.cierre), destino=args.destino, cache=not args.sin_cache)
        return _renombrar(salida, "cerrar")
    raise UsoInvalido("Comando desconocido")


def _despachar_nativo(repo, args):
    raiz = repo.raiz
    entrada = _leer(raiz, args.entrada_nativa)
    if any(getattr(args, clave, None) is not None for clave in ("acuerdo", "base", "cierre")):
        return informe_error(args.verbo, ErrorConvivencia(
            "Las referencias nativas se identifican en --entrada-nativa.", codigo="ENTRADA_NATIVA"))
    if args.verbo == "iniciar":
        return iniciar(raiz, args.sesion, entrada_nativa=entrada)
    preparacion = _leer(raiz, args.preparacion, informe=True)
    dictamenes = _dictamenes(raiz, args.dictamenes)
    if args.verbo == "validar":
        return _validar_nativo_cli(repo, args, entrada, preparacion, dictamenes)
    if args.verbo == "verificar":
        if args.salida is not None:
            return informe_error("verificar", ErrorConvivencia(
                "El perfil nativo devuelve el informe por stdout; publique mediante su lote ordinario.",
                codigo="PUBLICACION_NATIVA"))
        informe = verificar(raiz, args.sesion, arbol=args.arbol, etapa=args.etapa, entrada_nativa=entrada,
                            preparacion=preparacion, dictamenes=dictamenes,
                            esperados_rojos=_leer(raiz, args.esperados_rojos, {}), timeout=args.timeout)
        salida = resultado("verificar", informe["errores"], codigo=informe["codigo"])
        salida.update(informe=informe, ruta_informe=None, limites=informe["limites"],
                      perfil_operacion=repo.perfil, resumen=informe["resumen"])
        return salida
    if args.preparar:
        if not args.informe:
            raise UsoInvalido("--informe es obligatorio para cerrar --preparar")
        salida = preparar_cierre(raiz, args.sesion, _leer(raiz, args.informe, informe=True),
                                destino=args.destino, entrada_nativa=entrada)
    else:
        if not args.integracion:
            raise UsoInvalido("--integracion es obligatorio para cerrar --confirmar")
        if args.informe is not None:
            raise UsoInvalido("Identifica la suite y demás referencias post-main en --entrada-nativa")
        salida = confirmar_cierre(raiz, args.sesion, args.integracion, destino=args.destino,
                                 cache=False, entrada_nativa=entrada)
    return _renombrar(salida, "cerrar")


def _validar_nativo_cli(repo, args, entrada, preparacion, dictamenes):
    if (args.modo != "borrador" or args.plan_guardado or args.planificar_guardado) and not args.sesion:
        raise UsoInvalido("--sesion es obligatorio para validar trabajo, entrega o lote")
    if args.plan_guardado:
        lote = _leer(repo.raiz, args.plan_guardado)
        if isinstance(lote, dict) and "lote" in lote:
            lote = lote["lote"]
        salida = conciliar_guardado(repo.raiz, args.sesion, lote, arbol=args.arbol, entrada_nativa=entrada,
                                   preparacion=preparacion, dictamenes=dictamenes)
    elif args.planificar_guardado:
        if args.modo != "trabajo" or args.arbol != "staged":
            raise UsoInvalido("--planificar-guardado exige --modo trabajo --arbol staged")
        salida = planificar_guardado(repo.raiz, args.sesion, entrada_nativa=entrada,
                                     preparacion=preparacion, dictamenes=dictamenes)
    elif args.modo == "entrega":
        if not args.informe:
            raise UsoInvalido("--informe es obligatorio para validar entrega")
        salida = evaluar_entrega(repo.raiz, args.sesion, _leer(repo.raiz, args.informe, informe=True),
                                 arbol=args.arbol, entrada_nativa=entrada)
    else:
        salida = validar(repo.raiz, arbol=args.arbol)
        if salida["codigo"] == 0 and args.modo == "trabajo":
            from ..nucleo.inicio import _preflight_guardado

            datos, evidencia = _preflight_guardado(repo, args.sesion, entrada, (), preparacion, dictamenes)
            salida.update(acuerdo=datos, evidencia=evidencia)
    return _renombrar(salida, "validar", modo=args.modo, arbol=args.arbol)


def ejecutar(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    operacion = next((v for v in argv if v in {"contexto", "validar", "iniciar", "verificar", "cerrar", "sdd", "ruta", "tablero"}), "cli")
    try:
        args = _parser().parse_args(argv)
        return _despachar(args)
    except SystemExit as exc:
        if exc.code == 0:
            salida = resultado("ayuda")
            salida["_ayuda"] = True
            return salida
        raise
    except UsoInvalido as exc:
        return resultado(operacion, [diagnostico("USO_INVALIDO", "argumentos", "Opciones de la ayuda pública",
                                              str(exc), "Consulta --help del comando.")], codigo=2)
    except ErrorConvivencia as exc:
        return informe_error(operacion, exc)
    except Exception as exc:
        return resultado(operacion, [diagnostico("OPERACION_FALLIDA", "comando", "Operación del núcleo satisfecha",
                                              str(exc) or type(exc).__name__, "Corrige la causa y repite la operación.")], codigo=1)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    salida = ejecutar(argv)
    if salida.get("_ayuda"):
        return salida["codigo"]
    datos_nativos = salida.get("perfil_operacion") == "heimdall-v2" and any(
        salida.get(campo) is not None for campo in ("lote", "candidato", "informe"))
    if "--json" in argv or datos_nativos:
        print(json.dumps(salida, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{salida['operacion']}: {salida['estado']} (código {salida['codigo']})")
        print(salida["resumen"])
        if salida.get("ruta_informe"):
            print("Informe:", salida["ruta_informe"])
        for error in salida["errores"]:
            print(f"{error['codigo']} · {error['ruta']}: {error['mensaje']}")
    return salida["codigo"]
