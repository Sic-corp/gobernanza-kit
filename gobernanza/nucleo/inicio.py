"""Inicio y persistencia documental segura de F-0106, sin hooks ni filtros.

Las escrituras son operaciones explícitas del caller. No se crean ramas ni se
integran destinos; Git conserva el acuerdo fuente, no una firma del propietario.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import uuid

from .acuerdos import (_capturar, _commit, _salidas, _zonas_solapadas,
                       capturar_acuerdo, normalizar_autoridad)
from .arboles import (LectorArbol, _clave_portable, _leer_trabajo, _raiz_repositorio,
                      _ruta, materializar)
from .convivencia import (OID, PERFIL, RepositorioNativo, huella_bytes, huella_datos,
                          seleccionar_perfil)
from .documentos import Repositorio, json_estricto
from .modelo import coincide, diagnostico, resultado
from .verificacion import _hash, validar_preparacion_nativa


class ErrorInicio(ValueError):
    """Persistencia documental no segura o autoridad no utilizable."""


def _entorno():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
    return env


def _git(raiz, *args, entrada=None, indice=None, identidad=None, worktree=None, gitdir=None):
    env = _entorno()
    if indice is not None:
        if worktree is None or gitdir is None or any(Path(worktree).iterdir()):
            raise ErrorInicio("Las operaciones de índice alternativo requieren un worktree vacío explícito.")
        env["GIT_INDEX_FILE"] = str(indice)
        env["GIT_DIR"] = str(gitdir)
        env["GIT_WORK_TREE"] = str(worktree)
    if identidad is not None:
        nombre, correo = identidad
        env.update(GIT_AUTHOR_NAME=nombre, GIT_AUTHOR_EMAIL=correo,
                   GIT_COMMITTER_NAME=nombre, GIT_COMMITTER_EMAIL=correo)
    try:
        p = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                            "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
                           cwd=worktree if indice is not None else raiz,
                           env=env, input=entrada, capture_output=True)
    except (OSError, ValueError) as exc:
        raise ErrorInicio(f"Git no disponible: {exc}") from exc
    if p.returncode:
        raise ErrorInicio(p.stderr.decode("utf-8", errors="replace").strip() or "Git rechazó la operación documental.")
    return p.stdout


def _identidad(raiz):
    valores = []
    for clave in ("user.name", "user.email"):
        valor = None
        for ambito in ("--local", "--global"):
            env = _entorno()
            if ambito == "--global":
                env.pop("GIT_CONFIG_GLOBAL", None)
            p = subprocess.run(["git", "config", ambito, "--get", clave], cwd=raiz,
                               env=env, capture_output=True)
            if p.returncode == 0:
                valor = p.stdout.decode("utf-8").strip()
                break
        if not valor or any(c in valor for c in "\n\r\x00"):
            raise ErrorInicio(f"Falta identidad Git válida: {clave}; configura tu identidad antes de guardar.")
        valores.append(valor)
    return tuple(valores)


def _raiz(raiz):
    try:
        return _raiz_repositorio(raiz)
    except (ValueError, OSError, TypeError) as exc:
        raise ErrorInicio(str(exc)) from exc


def _ruta_documental(ruta):
    try:
        ruta = _ruta(ruta)
    except (ValueError, TypeError) as exc:
        raise ErrorInicio(str(exc)) from exc
    if any(_clave_portable(p) == ".git" for p in PurePosixPath(ruta).parts):
        raise ErrorInicio("Los destinos públicos no pueden escribir metadatos Git.")
    return ruta


def _json(datos):
    try:
        return (json.dumps(datos, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ErrorInicio(f"JSON no serializable de forma segura: {exc}") from exc


def _leer(raiz, ruta):
    _ruta_documental(ruta)
    try:
        leido = _leer_trabajo(raiz, ruta)
    except (ValueError, OSError) as exc:
        raise ErrorInicio(str(exc)) from exc
    if leido is not None and leido[0] == "120000":
        raise ErrorInicio(f"Un documento de persistencia no puede ser un enlace: {ruta}")
    return leido


@contextmanager
def _padre(raiz, ruta, crear=False):
    """Abre cada directorio sin seguir enlaces; conserva fds durante la escritura."""
    partes = PurePosixPath(_ruta_documental(ruta)).parts
    abiertos, creados = [], []
    correcto = False
    try:
        fd = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        abiertos.append(fd)
        for parte in partes[:-1]:
            try:
                siguiente = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not crear:
                    raise
                os.mkdir(parte, mode=0o755, dir_fd=fd)
                creados.append((fd, parte))
                siguiente = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            abiertos.append(siguiente)
            fd = siguiente
        yield fd, partes[-1]
        correcto = True
    finally:
        if not correcto:
            for directorio, nombre in reversed(creados):
                try:
                    os.rmdir(nombre, dir_fd=directorio)
                except OSError:
                    pass
        for descriptor in reversed(abiertos):
            os.close(descriptor)


def _escribir_bytes(raiz, ruta, contenido, *, exclusivo=False, modo="100644"):
    if not isinstance(contenido, bytes):
        raise ErrorInicio("El guardado documental requiere bytes explícitos.")
    with _padre(raiz, ruta, crear=True) as (padre, nombre):
        temporal = ".gobernanza-" + uuid.uuid4().hex + ".tmp"
        try:
            descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=padre)
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(contenido)
                archivo.flush()
                os.fchmod(archivo.fileno(), 0o755 if modo == "100755" else 0o644)
                os.fsync(archivo.fileno())
            if exclusivo:
                os.link(temporal, nombre, src_dir_fd=padre, dst_dir_fd=padre, follow_symlinks=False)
            else:
                os.replace(temporal, nombre, src_dir_fd=padre, dst_dir_fd=padre)
        finally:
            try:
                os.unlink(temporal, dir_fd=padre)
            except FileNotFoundError:
                pass


def _eliminar(raiz, ruta):
    try:
        with _padre(raiz, ruta) as (padre, nombre):
            os.unlink(nombre, dir_fd=padre)
    except FileNotFoundError:
        pass


def escribir_json_seguro(raiz, ruta, datos):
    """Crea JSON exclusivamente, o devuelve el mismo archivo idéntico sin escribir."""
    raiz = _raiz(raiz)
    _exigir_guardado_original(raiz)
    ruta = _ruta_documental(ruta)
    contenido = _json(datos)
    try:
        previo = _leer(raiz, ruta)
        if previo is not None:
            if previo[1] != contenido:
                raise ErrorInicio(f"El destino ya contiene un archivo diferente: {ruta}")
            return ruta
        _escribir_bytes(raiz, ruta, contenido, exclusivo=True)
        return ruta
    except OSError as exc:
        raise ErrorInicio(f"No se pudo publicar {ruta}: {exc}") from exc


def _entradas_indice(raiz):
    entradas = {}
    for registro in _git(raiz, "ls-files", "--stage", "-z").split(b"\0"):
        if not registro:
            continue
        cabecera, nombre = registro.split(b"\t", 1)
        modo, oid, etapa = cabecera.decode("ascii").split()
        entradas.setdefault(nombre.decode("utf-8"), []).append((modo, oid, etapa))
    return entradas


def _limpias(raiz, rutas, head):
    """Solo inspecciona las rutas propias; conflictos ajenos no se descartan."""
    indice = _entradas_indice(raiz)
    previos = {}
    with materializar(raiz, head) as fuente:
        for ruta in rutas:
            actual = _leer(raiz, ruta)
            esperado = fuente.archivos.get(ruta)
            registrados = indice.get(ruta, [])
            if esperado is None:
                if actual is not None or registrados:
                    raise ErrorInicio(f"El destino nuevo ya tiene contenido o staging ajeno: {ruta}")
            else:
                if esperado["modo"] not in {"100644", "100755"} or actual is None:
                    raise ErrorInicio(f"Documento propio no regular o eliminado: {ruta}")
                contenido = (fuente.raiz / ruta).read_bytes()
                if actual != (esperado["modo"], contenido) or len(registrados) != 1:
                    raise ErrorInicio(f"La ruta propia tiene cambios sin guardar: {ruta}")
                modo, oid, etapa = registrados[0]
                if etapa != "0" or modo != esperado["modo"] or _git(raiz, "cat-file", "blob", oid) != contenido:
                    raise ErrorInicio(f"La ruta propia contiene staging diferente de HEAD: {ruta}")
            # Rechaza aliases del índice en un filesystem insensible a casing/NFC.
            if any(_clave_portable(r) == _clave_portable(ruta) and r != ruta for r in indice):
                raise ErrorInicio(f"Alias de ruta documental en el índice: {ruta}")
            previos[ruta] = actual
    return previos


def _validar_lote(documentos):
    if not isinstance(documentos, dict) or not documentos:
        raise ErrorInicio("El lote documental debe contener rutas y bytes.")
    claves = {}
    for ruta, contenido in documentos.items():
        _ruta_documental(ruta)
        if not isinstance(contenido, bytes):
            raise ErrorInicio("Cada documento del lote requiere bytes.")
        clave = _clave_portable(ruta)
        if clave in claves:
            raise ErrorInicio("El lote contiene aliases de una misma ruta.")
        claves[clave] = ruta
    for ruta in documentos:
        if any(_clave_portable(p.as_posix()) in claves for p in PurePosixPath(ruta).parents):
            raise ErrorInicio("Un documento del lote se usa como directorio de otro.")


def _guardar_documentos(raiz, documentos, mensaje, *, esperado=None, refs_esperadas=None):
    """Commit solo de rutas propias; conserva blobs, modos y etapas ajenos.

    esperado fija HEAD; refs_esperadas se verifica en la misma transacción que
    mueve únicamente la rama actual. Un fallo normal restaura archivos e índice.
    Una interrupción de proceso conserva el commit/ref o el lock para recuperación;
    no se promete atomicidad física entre Git y todos los archivos del filesystem.
    """
    raiz = _raiz(raiz)
    _validar_lote(documentos)
    if not isinstance(mensaje, str) or not mensaje.strip() or "\x00" in mensaje:
        raise ErrorInicio("El guardado requiere mensaje Git no vacío.")
    head = _commit(raiz, "HEAD")
    if esperado is not None and _commit(raiz, esperado) != head:
        raise ErrorInicio("HEAD cambió respecto del guardado esperado.")
    rama = _git(raiz, "symbolic-ref", "--quiet", "HEAD").strip().decode("utf-8")
    refs_esperadas = {} if refs_esperadas is None else refs_esperadas
    if not isinstance(refs_esperadas, dict):
        raise ErrorInicio("refs_esperadas debe ser un mapa ref completa a SHA.")
    refs = {}
    for ref, sha in refs_esperadas.items():
        if not isinstance(ref, str) or not ref.startswith("refs/"):
            raise ErrorInicio("Las referencias verificadas requieren nombre Git completo.")
        _git(raiz, "check-ref-format", ref)
        refs[ref] = _commit(raiz, sha)
        if _commit(raiz, ref) != refs[ref]:
            raise ErrorInicio(f"La referencia esperada cambió: {ref}")
        if ref == rama and refs[ref] != head:
            raise ErrorInicio("La referencia de la rama no coincide con HEAD.")
    identidad = _identidad(raiz)
    gitdir = Path(os.fsdecode(_git(raiz, "rev-parse", "--absolute-git-dir").strip()))
    indice = Path(os.fsdecode(_git(raiz, "rev-parse", "--git-path", "index").strip()))
    if not indice.is_absolute():
        indice = raiz / indice
    if indice.is_symlink():
        raise ErrorInicio("El índice Git no puede ser un enlace.")
    lock = indice.with_name(indice.name + ".lock")
    descriptor = None
    publicados, previos = [], {}
    nuevo_commit = None
    ref_movida = False
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        if _commit(raiz, "HEAD") != head or _git(raiz, "symbolic-ref", "--quiet", "HEAD").strip().decode("utf-8") != rama:
            raise ErrorInicio("La rama o HEAD cambiaron antes del guardado.")
        previos = _limpias(raiz, documentos, head)
        if all(previos[r] is not None and previos[r][1] == contenido for r, contenido in documentos.items()):
            return head
        indice_original = indice.read_bytes()
        with tempfile.TemporaryDirectory(prefix="gobernanza-indice-") as temporal:
            temporal = Path(temporal)
            worktree_vacio = temporal / "worktree-vacio"
            worktree_vacio.mkdir()
            # Al escribir un índice Git puede refrescar entradas racily-clean y
            # aplicar filtros al leer archivos ajenos. No le damos acceso a esos
            # archivos: estos comandos solo reciben OIDs ya fijados, Gitdir real
            # y un worktree vacío, sin descartar flags ni etapas del índice.
            aislamiento = dict(worktree=worktree_vacio, gitdir=gitdir)
            indice_commit, indice_nuevo = temporal / "commit.index", temporal / "usuario.index"
            indice_nuevo.write_bytes(indice_original)
            _git(raiz, "read-tree", head, indice=indice_commit, **aislamiento)
            for ruta, contenido in documentos.items():
                oid = _git(raiz, "hash-object", "-w", "--stdin", entrada=contenido).strip().decode("ascii")
                modo = previos[ruta][0] if previos[ruta] is not None else "100644"
                for alternativo in (indice_commit, indice_nuevo):
                    _git(raiz, "update-index", "--add", "--cacheinfo", modo, oid, ruta,
                         indice=alternativo, **aislamiento)
            tree = _git(raiz, "write-tree", indice=indice_commit, **aislamiento).strip().decode("ascii")
            nuevo_commit = _git(raiz, "commit-tree", tree, "-p", head,
                                entrada=(mensaje.strip() + "\n").encode("utf-8"), identidad=identidad).strip().decode("ascii")
            indice_final = indice_nuevo.read_bytes()
        # No sobrescribe una edición que llegó mientras Git construía el commit.
        for ruta in documentos:
            if _leer(raiz, ruta) != previos[ruta]:
                raise ErrorInicio(f"El documento cambió durante el guardado: {ruta}")
        for ruta, contenido in documentos.items():
            modo = previos[ruta][0] if previos[ruta] is not None else "100644"
            _escribir_bytes(raiz, ruta, contenido, exclusivo=previos[ruta] is None, modo=modo)
            publicados.append(ruta)
        with os.fdopen(descriptor, "wb") as bloqueo:
            descriptor = None
            bloqueo.write(indice_final)
            bloqueo.flush()
            os.fsync(bloqueo.fileno())
        ordenes = ["start"]
        ordenes.extend(f"verify {ref} {sha}" for ref, sha in refs.items() if ref != rama)
        ordenes.extend([f"update {rama} {nuevo_commit} {head}", "prepare", "commit", ""])
        _git(raiz, "update-ref", "--no-deref", "--stdin", entrada="\n".join(ordenes).encode("utf-8"))
        ref_movida = True
        os.replace(lock, indice)
        return nuevo_commit
    except (ValueError, OSError, TypeError, UnicodeError) as exc:
        if ref_movida:
            try:
                _git(raiz, "update-ref", "--no-deref", rama, head, nuevo_commit)
            except ErrorInicio as recuperar:
                raise ErrorInicio(f"No se pudo completar ni revertir el guardado {nuevo_commit}: {recuperar}") from exc
        for ruta in reversed(publicados):
            previo = previos[ruta]
            if previo is None:
                _eliminar(raiz, ruta)
            else:
                _escribir_bytes(raiz, ruta, previo[1], modo=previo[0])
        raise ErrorInicio(f"Guardado documental rechazado: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Solo elimina un lock que esta operación consiguió crear.
        if previos or descriptor is not None or nuevo_commit is not None:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass


def guardar_documentos(raiz, documentos, mensaje, *, esperado=None, refs_esperadas=None):
    """API compartida de guardado acotado, con diagnóstico ErrorInicio uniforme."""
    try:
        _exigir_guardado_original(raiz)
        return _guardar_documentos(raiz, documentos, mensaje, esperado=esperado, refs_esperadas=refs_esperadas)
    except ErrorInicio:
        raise
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        raise ErrorInicio(str(exc)) from exc


def _id_sesion(sesion):
    if not isinstance(sesion, str) or re.fullmatch(r"[SG]\d{2}-\d{2}", sesion) is None:
        raise ErrorInicio("Identificador de sesión inválido.")
    return sesion


def _registro(sesion):
    return f"sesiones/estado/{_id_sesion(sesion)}/acuerdo.json"


def leer_inicio(raiz, sesion):
    """Lee la captura RAW y comprueba integridad y autoridad en su ref fuente."""
    raiz = _raiz(raiz)
    ruta = _registro(sesion)
    try:
        head = _commit(raiz, "HEAD")
        _limpias(raiz, [ruta], head)
        leido = _leer(raiz, ruta)
        if leido is None:
            raise ErrorInicio("No existe un acuerdo de inicio persistido.")
        captura = json_estricto(leido[1].decode("utf-8"))
        if not isinstance(captura, dict) or captura.get("sesion") != sesion:
            raise ErrorInicio("El registro no corresponde a esta sesión.")
        anclada = _capturar(raiz, sesion, captura["ref_acuerdo"], captura["base"])
        if captura != anclada:
            raise ErrorInicio("La captura persistida no corresponde al acuerdo fuente en Git.")
        return captura
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        raise ErrorInicio(str(exc)) from exc


def _actualizar_sesion(contenido, ruta_registro, ref_acuerdo):
    lineas = contenido.decode("utf-8").splitlines(keepends=True)
    fin = next(i for i in range(1, len(lineas)) if lineas[i].rstrip("\r\n") == "---")
    datos = json_estricto("".join(lineas[1:fin]))
    if "inicio" in datos:
        raise ErrorInicio("La sesión ya contiene metadatos de inicio sin registro válido.")
    datos.update(estado="preparacion", inicio={"registro": ruta_registro, "ref_acuerdo": ref_acuerdo})
    return ("---\n" + json.dumps(datos, sort_keys=True, ensure_ascii=False) + "\n---\n" + "".join(lineas[fin + 1:])).encode("utf-8")


def _fallo(operacion, exc):
    return resultado(operacion, [diagnostico(operacion.upper() + "_INVALIDO", ".",
        "Autoridad anclada y persistencia documental segura", str(exc) or type(exc).__name__,
        "Conserva los documentos propios sin cambios y corrige la referencia o el destino indicado.")])


def iniciar(raiz, sesion, *, base=None, entrada_nativa=None):
    try:
        nativo = seleccionar_perfil(raiz, "HEAD", requiere_nativo=entrada_nativa is not None)
        if nativo is not None:
            if base is not None:
                raise ErrorInicio("Incluye la base nativa en la entrada del acuerdo.")
            return _iniciar_nativo(nativo, sesion, entrada_nativa)
        raiz = _raiz(raiz)
        registro = _registro(sesion)
        head = _commit(raiz, "HEAD")
        from .registro_sdd import auditar
        from .documentos import cargar
        errores = auditar(raiz, head)
        if errores:
            return resultado("iniciar", errores)
        with materializar(raiz, head) as vista:
            repo = cargar(vista.raiz)
            autoridad = normalizar_autoridad(vista.raiz, sesion)
            for ref in autoridad["datos"]["funcionalidades"]:
                repo.resolver(ref, autoridad["ruta_sesion"])
            if repo.errores:
                return resultado("iniciar", repo.errores)
        if _leer(raiz, registro) is not None:
            acuerdo = leer_inicio(raiz, sesion)
            if base is not None and _commit(raiz, base) != acuerdo["base"]:
                raise ErrorInicio("La base indicada difiere del inicio persistido.")
            _limpias(raiz, [acuerdo["ruta_sesion"]], head)
            with materializar(raiz, head) as vista:
                actual = normalizar_autoridad(vista.raiz, sesion)
            if actual["datos"] != acuerdo["datos"] or actual["huella_acuerdo"] != acuerdo["huella_acuerdo"]:
                raise ErrorInicio("La autoridad cambió después del inicio; no se reemplaza el acuerdo persistido.")
            guardado = _git(raiz, "log", "-1", "--format=%H", "--", registro).strip().decode("ascii")
            idempotente = True
        else:
            es_sdd = autoridad["ruta_sesion"].startswith("sdd/registro/")
            fuente = head
            if es_sdd:
                from .registro_sdd import listar_operaciones
                for operacion in reversed(listar_operaciones(raiz, head)):
                    if any(c["ref"] == sesion and c["estado"] == "preparacion"
                           for c in operacion["cambios"]):
                        fuente = operacion["commit"]
                        break
                else:
                    raise ErrorInicio("Falta una promoción registrada a preparación.")
            acuerdo = _capturar(raiz, sesion, fuente, base)
            if acuerdo["huella_acuerdo"] != autoridad["huella_acuerdo"]:
                raise ErrorInicio("La promoción y el candidato contienen acuerdos diferentes.")
            _limpias(raiz, [registro, acuerdo["ruta_sesion"]], head)
            escrituras = {registro: _json(acuerdo)}
            if not es_sdd:
                original = _leer(raiz, acuerdo["ruta_sesion"])[1]
                escrituras[acuerdo["ruta_sesion"]] = _actualizar_sesion(original, registro, acuerdo["ref_acuerdo"])
            guardado = guardar_documentos(raiz, escrituras,
                                         f"docs: iniciar {sesion} con acuerdo fuente", esperado=head)
            idempotente = False
        salida = resultado("iniciar")
        salida.update(acuerdo=acuerdo, registro=registro, ref_guardado=guardado, idempotente=idempotente,
                      resumen="Inicio documental conservado; no concede permisos nuevos ni acepta entrega.")
        return salida
    except (ValueError, OSError, TypeError, KeyError, UnicodeError, StopIteration) as exc:
        salida = _fallo("iniciar", exc)
        salida.update(acuerdo=None, registro=None, ref_guardado=None, idempotente=False)
        return salida


def publicar_informe(raiz, sesion, informe, *, destino=None):
    try:
        raiz = _raiz(raiz)
        _id_sesion(sesion)
        _exigir_guardado_original(raiz)
        if (not isinstance(informe, dict) or type(informe.get("schema")) is not int or informe["schema"] != 1
                or informe.get("operacion") != "verificar" or informe.get("sesion") != sesion
                or informe.get("etapa") not in {"preparacion", "entrega"}):
            raise ErrorInicio("El informe no corresponde a una verificación de esta sesión y esquema.")
        huella = informe.get("huella_informe")
        if huella != _hash({k: v for k, v in informe.items() if k != "huella_informe"}):
            raise ErrorInicio("El informe fue alterado o no conserva su huella íntegra.")
        repo = Repositorio(raiz)
        if not repo.cargar_config():
            raise ErrorInicio("Configuración de publicación inválida.")
        config = repo.config
        if "proyecto" in informe and informe["proyecto"] != config["proyecto"]:
            raise ErrorInicio("El informe pertenece a otro proyecto.")
        salidas = _salidas(config)
        entradas = ["gobernanza/config.json", "sdd/proyecto.md", *config["documentos"],
                    *[ruta for grupo in config["raices"].values() for ruta in grupo]]
        if any(_zonas_solapadas(salida, entrada) for salida in salidas for entrada in entradas):
            raise ErrorInicio("Las salidas se solapan con entradas verificables.")
        ruta = destino if destino is not None else f"sesiones/evidencias/{sesion}/{informe['etapa']}-{huella}.json"
        ruta = _ruta_documental(ruta)
        if not any(coincide(ruta, salida) for salida in salidas):
            raise ErrorInicio("El destino no pertenece a las salidas declaradas.")
        escribir_json_seguro(raiz, ruta, informe)
        salida = resultado("publicar_informe")
        salida.update(ruta_informe=ruta, resumen="Informe íntegro publicado; un fallo publicado conserva su diagnóstico y no acepta entrega.")
        return salida
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as exc:
        salida = _fallo("publicar_informe", exc)
        salida["ruta_informe"] = None
        return salida


def _exigir_guardado_original(raiz):
    try:
        nativo = seleccionar_perfil(raiz, "HEAD")
    except (ValueError, OSError) as exc:
        raise ErrorInicio(str(exc)) from exc
    if nativo is not None:
        raise ErrorInicio("El perfil Heimdall sólo admite planificación, Git ordinario y conciliación.")


def _entrada_lote(entrada):
    if not isinstance(entrada, dict):
        raise ErrorInicio("Se requiere una entrada nativa JSON con actor, transacción y acuerdo.")
    return entrada


def _lector(repo, arbol):
    return LectorArbol(repo.raiz, arbol)


def _padres_nativos(repo, commit):
    datos = repo.git("rev-list", "--parents", "-n", "1", commit).decode("ascii").split()
    if not datos or datos[0] != commit:
        raise ErrorInicio("No se pudieron cotejar los padres del commit literal.")
    return datos[1:]


def _foto(lector, ruta):
    entrada = lector.entrada(ruta)
    return _huella_imagen(entrada) if entrada is not None else None


def _huella_imagen(imagen):
    modo, contenido = imagen
    if modo not in ("100644", "100755"):
        raise ErrorInicio("Sólo se admiten archivos regulares en el lote.")
    return {"modo": modo, "sha256": huella_bytes(contenido)}


def _rutas_cambiadas(antes, despues):
    return sorted(ruta for ruta in antes.entradas.keys() | despues.entradas.keys()
                  if antes.entradas.get(ruta) != despues.entradas.get(ruta))


def _diff_lote(antes, despues, rutas):
    return {ruta: {"antes": _foto(antes, ruta), "despues": _foto(despues, ruta)}
            for ruta in rutas}


def _sin_deriva_local(repo, lote):
    for ruta, versiones in lote["rutas"].items():
        imagen = _leer_trabajo(repo.raiz, ruta)
        if (_huella_imagen(imagen) if imagen is not None else None) != versiones["despues"]:
            raise ErrorInicio(f"El worktree difiere del índice en la ruta del lote: {ruta}.")


def _cabecera_lote(repo, datos, folio, fase, cabeza, rutas, *, mensaje=None, evidencias=None):
    if fase == "activacion":
        rama = f"codex/{folio}/{datos['transaccion']}"
        rama_origen = f"codex/PLANIFICACION/{datos['transaccion']}"
    else:
        rama, rama_origen = repo.rama, repo.rama
    plan = datos["plan"]
    lote = {
        "schema": 1, "perfil_operacion": PERFIL, "proyecto": repo.proyecto,
        "raiz": str(repo.raiz), "raiz_comun": str(repo.comun), "rama": rama, "rama_origen": rama_origen, "folio": folio,
        "actor": datos["actor"], "transaccion": datos["transaccion"], "base": datos["base"],
        "head": cabeza, "fase": fase, "ref_acuerdo": datos["ref_acuerdo"],
        "huella_acuerdo": datos["huella_acuerdo"], "plan": plan["ruta"],
        "ref_plan": datos["ref_acuerdo"], "blob_plan": datos.get("blob", plan["blob"]), "alcance": plan["alcance"],
        "rutas": rutas, "mensaje": mensaje, "evidencias": evidencias or {},
    }
    return dict(lote, huella=huella_datos(lote))


def _respuesta_lote(operacion, lote=None, *, guardado=None, **datos):
    salida = resultado(operacion)
    salida.update(perfil_operacion=PERFIL, lote=lote, ref_guardado=guardado, **datos)
    salida["resumen"] = "Cotejo en lectura sobre las entradas de Git; el escritor conserva el guardado ordinario."
    return salida


def _imagen_propuesta(imagen, ruta):
    if not isinstance(imagen, dict) or set(imagen) != {"modo", "texto"} or not isinstance(imagen["texto"], str):
        raise ErrorInicio(f"Imagen inválida: {ruta}. Se requiere modo Git y texto UTF-8.")
    return imagen["modo"], imagen["texto"].encode("utf-8")


class _ImagenesActivacion(LectorArbol):
    """Vista de sólo lectura sobre HEAD y los bytes entregados por el escritor."""

    def __init__(self, repo, imagenes):
        super().__init__(repo.raiz, repo.head)
        self.arbol = "propuesta"
        self.commit = None
        self.imagenes = imagenes
        self.rutas.update(imagenes)

    def entrada(self, ruta):
        if ruta in self.imagenes:
            return self.imagenes[self.comprobar_ruta(ruta)]
        # El lector regular debe seguir consultando HEAD para otras rutas.
        return super().entrada(ruta)

    def blob(self, ruta, contenido, *, longitud):
        if ruta not in self.imagenes:
            return super().blob(ruta, contenido, longitud=longitud)
        algoritmo = "sha256" if longitud == 64 else "sha1"
        return hashlib.new(algoritmo, f"blob {len(contenido)}\0".encode() + contenido).hexdigest()


def _transicion_nativa(antes, despues, estado):
    estables = ("folio", "dominio", "proyecto", "perfil", "modulo", "version", "ruta",
                "evidencia", "continuidad", "estado_modulo", "alcance", "contratos",
                "funcionalidades", "base", "cita", "aprobaciones", "transaccion")
    if despues["estado"] != estado or any(antes[c] != despues[c] for c in estables):
        raise ErrorInicio(f"La transición a {estado} cambia la identidad o autoridad del plan.")


def _iniciar_nativo(repo, folio, entrada):
    from .acuerdos import preflight_activacion_nativo, preflight_nativo

    entrada = _entrada_lote(entrada)
    plan = repo.plan(folio)
    if plan["estado"] == "Activo":
        if entrada.get("imagenes") is not None:
            raise ErrorInicio("La retoma usa el plan Activo guardado y no recibe imágenes.")
        datos = preflight_nativo(repo, folio, entrada)
        guardado = repo.git("log", "-1", "--format=%H", repo.head, "--", plan["ruta"]).decode().strip()
        return _respuesta_lote("iniciar", guardado=guardado, acuerdo=datos, idempotente=True)
    if plan["estado"] != "Borrador":
        raise ErrorInicio("El inicio requiere el Borrador aprobado o el plan Activo guardado.")
    if repo.rama != f"codex/PLANIFICACION/{entrada.get('transaccion')}":
        raise ErrorInicio("Planifica la activación desde la rama de planificación de la transacción.")
    imagenes = entrada.get("imagenes")
    autorizables = {plan["ruta"], plan["estado_modulo"], plan["evidencia"]}
    if not isinstance(imagenes, dict) or plan["ruta"] not in imagenes or set(imagenes) - autorizables:
        raise ErrorInicio("La activación necesita imágenes del plan y documentos propios aprobados.")
    imagenes = {ruta: _imagen_propuesta(imagen, ruta) for ruta, imagen in imagenes.items()}
    nuevo = RepositorioNativo(repo.raiz, _ImagenesActivacion(repo, imagenes), repo.config,
                              historico=False, head=repo.head)
    propuesta = nuevo.plan(folio)
    datos = preflight_activacion_nativo(repo, folio, entrada, propuesta=propuesta, rutas=imagenes)
    rutas = {ruta: {"antes": _foto(repo.lector, ruta), "despues": _huella_imagen(imagen)}
             for ruta, imagen in sorted(imagenes.items())}
    if any(versiones["antes"] == versiones["despues"] for versiones in rutas.values()):
        raise ErrorInicio("Una imagen de activación no introdujo un cambio.")
    lote = _cabecera_lote(repo, datos, folio, "activacion", repo.head, rutas)
    return _respuesta_lote("iniciar", lote, acuerdo=datos, idempotente=False)


def planificar_guardado(raiz, sesion, *, entrada_nativa, preparacion=None, dictamenes=()):
    """Propone un lote en el índice completo, con los archivos ajenos preservados."""
    try:
        entrada = _entrada_lote(entrada_nativa)
        repo = seleccionar_perfil(raiz, "staged", requiere_nativo=True)
        cabeza = _lector(repo, repo.head)
        rutas = _rutas_cambiadas(cabeza, repo.lector)
        if not rutas:
            raise ErrorInicio("El índice no contiene cambios para guardar.")
        datos, evidencias = _preflight_guardado(repo, sesion, entrada, rutas, preparacion, dictamenes)
        lote = _cabecera_lote(repo, datos, sesion, "ejecucion", repo.head, _diff_lote(cabeza, repo.lector, rutas),
                              evidencias=evidencias)
        _sin_deriva_local(repo, lote)
        _comprobar_indice_actual(repo, cabeza, lote)
        return _respuesta_lote("planificar_guardado", lote)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return _fallo("planificar_guardado", exc)


def _preflight_guardado(repo, folio, entrada, rutas, preparacion, dictamenes):
    from .acuerdos import _cambios_fuente, comprobar_autoridad_nativa, preflight_nativo

    autoridad = comprobar_autoridad_nativa(repo, folio, entrada)
    base = _lector(repo, autoridad["base"])
    cambios = _cambios_fuente(base, repo.lector)
    datos = preflight_nativo(repo, folio, entrada, rutas=set(rutas) | cambios)
    if datos["huella_acuerdo"] != autoridad["huella_acuerdo"]:
        raise ErrorInicio("Cambió el acuerdo durante el preflight del guardado.")
    verificado = validar_preparacion_nativa(repo, datos, preparacion=preparacion, dictamenes=dictamenes)
    return datos, {
        "preparacion": preparacion and preparacion.get("huella_informe"),
        "dictamenes": huella_datos(dictamenes), "huella_entradas": verificado["huella_entradas"],
        "huella_obligaciones": verificado["huella_obligaciones"],
    }


def _comprobar_indice_actual(repo, padre, lote):
    actual = seleccionar_perfil(repo.raiz, "staged", requiere_nativo=True)
    if (actual.head != repo.head or actual.rama != repo.rama
            or _diff_lote(padre, actual.lector, _rutas_cambiadas(padre, actual.lector)) != lote["rutas"]):
        raise ErrorInicio("El índice, HEAD o la rama cambiaron durante el cotejo.")
    _sin_deriva_local(actual, lote)


def _comprobar_forma_lote(repo, folio, lote, arbol):
    if (not isinstance(lote, dict) or type(lote.get("schema")) is not int or lote["schema"] != 1
            or not isinstance(lote.get("rutas"), dict)
            or not lote["rutas"] or lote.get("huella") != huella_datos({k: v for k, v in lote.items() if k != "huella"})
            or lote.get("raiz") != str(repo.raiz) or lote.get("raiz_comun") != str(repo.comun)
            or lote.get("rama") != repo.rama or lote.get("folio") != folio
            or lote.get("proyecto") != repo.proyecto or lote.get("perfil_operacion") != PERFIL
            or not re.fullmatch(OID, str(lote.get("head", "")))):
        raise ErrorInicio("El lote no coincide con su huella, folio, rama o raíz Git.")
    if arbol == "staged":
        if repo.head != lote["head"]:
            raise ErrorInicio("HEAD cambió tras planificar el lote.")
    elif (not re.fullmatch(OID, arbol) or repo.commit != arbol
          or _padres_nativos(repo, arbol) != [lote["head"]]):
        raise ErrorInicio("El guardado observado debe ser el SHA exacto con el único padre del lote.")
    elif arbol != repo.head:
        previos = repo.git("rev-list", "--first-parent", f"{lote['head']}..{repo.head}")
        if arbol.encode("ascii") not in previos.splitlines():
            raise ErrorInicio("El commit observado no pertenece a la línea principal de la rama del lote.")


def _conciliar_imagenes(repo, folio, lote, arbol):
    _comprobar_forma_lote(repo, folio, lote, arbol)
    cabeza = _lector(repo, lote["head"])
    rutas = _rutas_cambiadas(cabeza, repo.lector)
    if _diff_lote(cabeza, repo.lector, rutas) != lote["rutas"]:
        raise ErrorInicio("El diff completo de Git diverge de las rutas, modos o bytes del lote.")
    if arbol == "staged":
        _comprobar_indice_actual(repo, cabeza, lote)
    else:
        _sin_deriva_local(repo, lote)
        if lote.get("mensaje") is not None:
            mensaje = repo.git("log", "-1", "--format=%B", arbol).decode("utf-8").rstrip("\n")
            if mensaje != lote["mensaje"]:
                raise ErrorInicio("El mensaje del commit difiere del mensaje literal acordado.")
    return rutas


def conciliar_guardado(raiz, sesion, lote, *, arbol, entrada_nativa, preparacion=None, dictamenes=()):
    """Coteja un lote con el índice vigente o con el commit ordinario observado."""
    from .acuerdos import preflight_activacion_nativo

    try:
        entrada = _entrada_lote(entrada_nativa)
        if arbol != "staged" and (not isinstance(arbol, str) or not re.fullmatch(OID, arbol)):
            raise ErrorInicio("Indica staged o el SHA literal del guardado de Git.")
        repo = seleccionar_perfil(raiz, arbol, requiere_nativo=True)
        rutas = _conciliar_imagenes(repo, sesion, lote, arbol)
        fase = lote["fase"]
        if fase == "cierre":
            from .cierre import conciliar_lote_cierre
            return conciliar_lote_cierre(repo, sesion, lote, arbol, entrada)
        if fase == "activacion":
            datos = preflight_activacion_nativo(repo, sesion, entrada, propuesta=repo.plan(sesion), rutas=rutas)
            evidencias = None
        elif fase == "ejecucion":
            datos, evidencias = _preflight_guardado(repo, sesion, entrada, rutas, preparacion, dictamenes)
        else:
            raise ErrorInicio("Fase de lote desconocida.")
        esperado = _cabecera_lote(repo, datos, sesion, fase, lote["head"], lote["rutas"], evidencias=evidencias)
        if lote != esperado:
            raise ErrorInicio("El lote difiere del acuerdo comprobado o de su evidencia.")
        return _respuesta_lote("conciliar_guardado", lote, guardado=repo.commit)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return _fallo("conciliar_guardado", exc)
