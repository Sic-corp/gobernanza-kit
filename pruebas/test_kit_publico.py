"""Ejercicios del kit con proyectos Git de ejemplo íntegramente temporales."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RAIZ = Path(__file__).resolve().parents[1]
MODULO = "M-TAREAS"
SPEC = "SPEC-0001@v1"
FUNCION = "F-0001@r1"
SESION = "S01-01"
TEXTO = "El título de una tarea se conserva.\n"


def ejecutar(argumentos, raiz):
    entorno = {
        k: v for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTHONHOME"} and not k.startswith("GIT_")
    }
    return subprocess.run(argumentos, cwd=raiz, env=entorno, capture_output=True,
                          text=True, timeout=30)


def git(raiz, *argumentos):
    resultado = ejecutar(["git", *argumentos], raiz)
    resultado.check_returncode()
    return resultado.stdout.strip()


def guardar(raiz):
    git(raiz, "add", ".")
    git(raiz, "-c", "core.hooksPath=/dev/null", "-c", "user.name=Ejemplo",
        "-c", "user.email=ejemplo@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-qm", "Guardar ejemplo")
    return git(raiz, "rev-parse", "HEAD")


def alta(tipo, ref, texto="", **campos):
    return {"accion": "alta", "texto": texto,
            "datos": dict(schema=3, tipo=tipo, ref=ref, estado="borrador", **campos)}


class KitPublicoTests(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.temporal = Path(temporal.name).resolve()
        self.proyecto = self.temporal / "tareas"
        self.proyecto.mkdir()
        git(self.proyecto, "init", "-q")
        git(self.proyecto, "config", "user.name", "Ejemplo")
        git(self.proyecto, "config", "user.email", "ejemplo@example.invalid")
        (self.proyecto / "README.md").write_text("# Tareas de ejemplo\n", encoding="utf-8")
        self.base = guardar(self.proyecto)

    def cli(self, *argumentos, codigo=0):
        salida = ejecutar([sys.executable, "-B", "-m", "gobernanza", *argumentos,
                           "--raiz", str(self.proyecto), "--json"], RAIZ)
        self.assertEqual(salida.returncode, codigo, salida.stderr + salida.stdout)
        return json.loads(salida.stdout)

    def proponer(self, seccion="ALTA"):
        documentos = [
            alta("modulo", MODULO),
            alta("spec", SPEC, "<!-- gobernanza:seccion ALTA -->\n" + TEXTO,
                 modulos=[MODULO], secciones=["ALTA"]),
            alta("funcionalidad", FUNCION, modulo=MODULO, criterios=["C01"],
                 secciones=[f"{SPEC}#{seccion}"]),
            alta("sesion", SESION, "# Plan de ejemplo\n", funcionalidades=[FUNCION], plan=1),
        ]
        entrada = self.temporal / "lote.json"
        entrada.write_text(json.dumps(dict(base=self.base, cambios=documentos)), encoding="utf-8")
        return entrada

    # gobernanza-test: {"id":"T-9001","criterio":"F-9000@r1/C01","verificador":"V-EJEMPLOS","selector":"test_kit_publico.KitPublicoTests.test_registra_y_reconstruye_un_contrato"}
    def test_registra_y_reconstruye_un_contrato(self):
        entrada = self.proponer()
        guardado = self.cli("sdd", "registrar", "--entrada", str(entrada), "--aplicar")
        self.assertEqual(guardado["commit"], git(self.proyecto, "rev-parse", "HEAD"))
        consulta = self.cli("sdd", "seccion", "--ref", f"{SPEC}#ALTA")
        self.assertEqual(consulta["texto"], TEXTO)
        traza = self.cli("sdd", "traza", "--sesion", SESION)
        self.assertEqual(traza["texto"], "# Plan de ejemplo\n")
        self.assertIn(f"{SPEC}#ALTA", traza["funcionalidades"][0]["secciones"])
        self.cli("sdd", "indice", "--escribir")
        self.cli("sdd", "indice", "--comprobar")
        self.assertIn(FUNCION, (self.proyecto / "sdd/indice.md").read_text(encoding="utf-8"))

    # gobernanza-test: {"id":"T-9002","criterio":"F-9000@r1/C01","verificador":"V-EJEMPLOS","selector":"test_kit_publico.KitPublicoTests.test_rechaza_una_seccion_ausente_sin_guardar"}
    def test_rechaza_una_seccion_ausente_sin_guardar(self):
        entrada = self.proponer(seccion="AUSENTE")
        resultado = self.cli("sdd", "registrar", "--entrada", str(entrada), "--aplicar", codigo=1)
        self.assertIn(f"{SPEC}#AUSENTE", json.dumps(resultado["errores"]))
        self.assertEqual(git(self.proyecto, "rev-parse", "HEAD"), self.base)
        self.assertFalse((self.proyecto / "sdd/registro").exists())

    # gobernanza-test: {"id":"T-9003","criterio":"F-9000@r1/C02","verificador":"V-EJEMPLOS","selector":"test_kit_publico.KitPublicoTests.test_instala_desde_un_artefacto_local_sin_la_fuente"}
    def test_instala_desde_un_artefacto_local_sin_la_fuente(self):
        from gobernanza.distribucion.entrega import crear_entrega

        fuente = self.temporal / "fuente"
        for nombre in ("gobernanza", "docs"):
            shutil.copytree(RAIZ / nombre, fuente / nombre,
                            ignore=shutil.ignore_patterns("__pycache__"))
        git(fuente, "init", "-q")
        artefacto = self.temporal / "artefacto"
        crear_entrega(fuente, guardar(fuente), artefacto, candidato=True)
        shutil.rmtree(fuente)
        plan = self.temporal / "plan.json"
        comandos = [
            ("planificar", "--accion", "instalar", "--modo", "aislado", "--salida", str(plan)),
            ("aplicar", "--plan", str(plan)),
            ("estado",),
        ]
        for argumentos in comandos:
            salida = ejecutar([sys.executable, "-I", str(artefacto / "instalar.py"),
                               "--raiz", str(self.proyecto), *argumentos, "--json"], self.temporal)
            self.assertEqual(salida.returncode, 0, salida.stderr + salida.stdout)
        self.assertTrue(json.loads(salida.stdout)["instalado"])
