"use client";

import Link from "next/link";
import {
  ArrowRight,
  Check,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { resetDemoState } from "@/lib/oracle/storage";
import "@/styles/showcase.css";

const tasks = [
  "Encontrar el expediente con mayor riesgo",
  "Localizar y abrir una señal nueva relevante",
  "Promover una señal a oportunidad o riesgo",
  "Crear un expediente de prueba",
  "Cambiar la densidad y comprobar su persistencia",
];

export default function Showcase() {
  const reset = () => {
    resetDemoState();
    toast.success("Demo restablecida", {
      description:
        "Se han eliminado expedientes, acciones y preferencias locales.",
    });
  };

  return (
    <main className="showcase">
      <header className="showcase-header">
        <div className="oracle-logo">
          <span className="oracle-mark">O</span>
          <span>
            OPN Oracle<small>Experiencia comparativa</small>
          </span>
        </div>
        <span className="synthetic-badge">
          <ShieldCheck size={13} /> Datos sintéticos
        </span>
      </header>

      <section className="showcase-hero">
        <div>
          <p className="eyebrow">
            <Sparkles size={14} /> Prototipo de decisión A/B
          </p>
          <h1>
            Dos formas de convertir un proyecto importante en un radar
            estratégico vivo.
          </h1>
        </div>
        <p>
          Explora los mismos expedientes y realiza las mismas tareas. Compara
          cómo cada concepto ayuda a detectar oportunidades, entender el
          contexto y decidir el siguiente movimiento.
        </p>
      </section>

      <section className="concept-grid">
        <article className="concept-card vector-card">
          <div className="concept-preview vector-preview" aria-hidden="true">
            <div className="mini-side">
              <i />
              <i />
              <i />
              <i />
              <i />
            </div>
            <div className="mini-main">
              <div className="mini-top" />
              <div className="mini-kpis">
                <b />
                <b />
                <b />
              </div>
              <div className="mini-table">
                <i />
                <i />
                <i />
                <i />
              </div>
            </div>
            <div className="mini-rail">
              <b />
              <i />
              <i />
            </div>
          </div>
          <div className="concept-copy">
            <div className="concept-index">Concepto A</div>
            <h2>Vector Command Center</h2>
            <p>
              Alta densidad y acceso inmediato. Diseñado para revisar muchas
              señales, priorizar trabajo y ejecutar acciones durante el día.
            </p>
            <ul>
              <li>Sidebar operativa persistente</li>
              <li>Tabla y bandejas como centro de trabajo</li>
              <li>Inspección rápida en panel lateral</li>
            </ul>
            <Link href="/concept-a/portfolio" className="open-link">
              Abrir Vector <ArrowRight size={17} />
            </Link>
          </div>
        </article>

        <article className="concept-card horizon-card">
          <div className="concept-preview horizon-preview" aria-hidden="true">
            <div className="horizon-mini-head">
              <i />
              <span />
              <span />
              <span />
            </div>
            <div className="horizon-mini-canvas">
              <div className="horizon-mini-rail">
                <b />
                <b />
                <b />
              </div>
              <div className="horizon-mini-board">
                <div />
                <div />
                <div />
              </div>
              <aside>
                <i />
                <i />
                <i />
              </aside>
            </div>
          </div>
          <div className="concept-copy">
            <div className="concept-index">Concepto B</div>
            <h2>Horizon Decision Canvas</h2>
            <p>
              Un canvas modular que hace visibles dependencias, señales y
              decisiones. Diseñado para trabajar por prioridades sin perder la
              evidencia que las sostiene.
            </p>
            <ul>
              <li>Navegación superior y carriles de decisión</li>
              <li>Contexto modular y evidencia en paralelo</li>
              <li>Acciones agrupadas por siguiente movimiento</li>
            </ul>
            <Link href="/concept-b/portfolio" className="open-link">
              Abrir Horizon <ArrowRight size={17} />
            </Link>
          </div>
        </article>
      </section>

      <section className="evaluation">
        <div>
          <p className="eyebrow">Guion de evaluación</p>
          <h2>Haz las mismas cinco tareas en ambos conceptos.</h2>
          <p>
            No hay un ganador predefinido: observa velocidad, orientación,
            confianza y facilidad para volver al contexto.
          </p>
        </div>
        <ol>
          {tasks.map((task) => (
            <li key={task}>
              <span>
                <Check size={15} />
              </span>
              {task}
            </li>
          ))}
        </ol>
      </section>
      <footer className="showcase-footer">
        <p>
          Estado local versionado · Fecha de referencia: 10 de julio de 2026
        </p>
        <button onClick={reset}>
          <RotateCcw size={15} /> Restablecer estado de la demo
        </button>
      </footer>
    </main>
  );
}
