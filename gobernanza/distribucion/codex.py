"""Reglas locales Codex activadas con autorización explícita del operador."""

import hashlib
import json
import os
from pathlib import Path
import re

from ..nucleo.arboles import _git, _leer_trabajo, _raiz_repositorio
from ..nucleo.inicio import _escribir_bytes


def preparar(raiz, sesion):
    raiz = _raiz_repositorio(raiz)
    if re.fullmatch(r"[GS][0-9]{2}-[0-9]{2}", sesion) is None:
        raise ValueError("Indica el ID de una sesión G o S, por ejemplo S01-01.")
    rama = _git(raiz, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    prefijo = f"codex/{sesion}/"
    if not rama.startswith(prefijo) or rama == prefijo:
        raise ValueError(f"El worktree debe estar en una rama de ejecución {prefijo}<slug>.")
    casa = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if not casa.is_absolute() or ".." in casa.parts or casa == Path(casa.anchor):
        raise ValueError("CODEX_HOME debe indicar un directorio absoluto de configuración.")
    ancla = Path(casa.anchor)
    clave = hashlib.sha256(os.fsencode(raiz)).hexdigest()
    destino = str(casa.relative_to(ancla) / "rules" / f"gobernanza-{clave}.rules")
    argumentos = ["git", "-C", str(raiz)]
    patrones = (
        ([*argumentos, "add", "--"], "allow"),
        ([*argumentos, "commit", "-m"], "allow"),
        (["git", "merge", "--no-ff", rama], "prompt"),
    )
    lineas = [
        f"# Gobernanza local: {rama}. Retirar al desocupar el worktree.",
        "# Revisar rama y rutas antes de guardar. Exigir aprobación humana para integrar.",
        *(f'prefix_rule(pattern = {json.dumps(patron)}, decision = "{decision}")'
          for patron, decision in patrones),
    ]
    contenido = ("\n".join(lineas) + "\n").encode("utf-8")
    _publicada(ancla, destino, contenido)
    return ancla, destino, contenido, rama


def _publicada(ancla, destino, contenido):
    previa = _leer_trabajo(ancla, destino)
    if previa is None:
        return False
    if previa != ("100644", contenido):
        raise ValueError(f"Regla local existente con contenido distinto: {ancla / destino}. Se conserva.")
    return True


def publicar(preparada):
    ancla, destino, contenido, rama = preparada
    existia = _publicada(ancla, destino, contenido)
    if not existia:
        try:
            _escribir_bytes(ancla, destino, contenido, exclusivo=True)
        except FileExistsError:
            if not _publicada(ancla, destino, contenido):
                raise
            existia = True
    return dict(archivo=str(ancla / destino), rama=rama, publicadas=True,
                idempotente=existia, requiere_reinicio=True)
