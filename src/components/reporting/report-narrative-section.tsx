"use client";

import type { ReactNode } from "react";

export type NarrativeClaimKind = "fact" | "inference" | "recommendation" | "decision";

export interface NarrativeParagraph {
  text: string;
  kind: NarrativeClaimKind;
  confidence: number;
  evidenceIds: string[];
}

interface NarrativeBlock {
  text: string;
  kinds: NarrativeClaimKind[];
  confidences: number[];
  evidenceIds: string[];
}

const MIN_WORDS_TO_STAND_ALONE = 55;
const MAX_MERGED_WORDS = 155;

function wordCount(value: string): number {
  return value.trim().split(/\s+/).filter(Boolean).length;
}

function uniqueValues<T>(values: T[]): T[] {
  return Array.from(new Set(values));
}

function appendSentence(left: string, right: string): string {
  if (!left) return right;
  return `${left.replace(/\s+$/, "")} ${right.replace(/^\s+/, "")}`;
}

function mergeNarrativeParagraphs(paragraphs: NarrativeParagraph[]): NarrativeBlock[] {
  const blocks: NarrativeBlock[] = [];
  let current: NarrativeBlock | null = null;

  for (const paragraph of paragraphs) {
    const text = paragraph.text.trim();
    if (!text) continue;
    const nextWords = wordCount(text);
    const currentWords = current ? wordCount(current.text) : 0;
    const canMerge =
      current !== null &&
      current.kinds.length === 1 &&
      current.kinds[0] === paragraph.kind &&
      currentWords < MIN_WORDS_TO_STAND_ALONE &&
      currentWords + nextWords <= MAX_MERGED_WORDS;

    if (canMerge && current) {
      current.text = appendSentence(current.text, text);
      current.confidences.push(paragraph.confidence);
      current.evidenceIds = uniqueValues([...current.evidenceIds, ...paragraph.evidenceIds]);
      continue;
    }

    current = {
      text,
      kinds: [paragraph.kind],
      confidences: [paragraph.confidence],
      evidenceIds: uniqueValues(paragraph.evidenceIds),
    };
    blocks.push(current);
  }

  return blocks;
}

function claimLabel(kind: NarrativeClaimKind): string {
  return {
    fact: "Hecho",
    inference: "Inferencia",
    recommendation: "Recomendación",
    decision: "Decisión",
  }[kind];
}

function confidenceLabel(values: number[]): string {
  const normalized = values
    .map((value) => Math.round(value))
    .filter((value) => Number.isFinite(value));
  if (!normalized.length) return "sin confianza explícita";
  const min = Math.min(...normalized);
  const max = Math.max(...normalized);
  return min === max ? `confianza ${min}%` : `confianza ${min}-${max}%`;
}

export function ReportNarrativeSection({
  heading,
  paragraphs,
  renderCitation,
}: {
  heading: string;
  paragraphs: NarrativeParagraph[];
  renderCitation: (evidenceId: string, citationIndex: number) => ReactNode;
}) {
  const blocks = mergeNarrativeParagraphs(paragraphs);

  return (
    <section className="report-section">
      <h2>{heading}</h2>
      <article className="report-section-summary">
        {blocks.length ? (
          blocks.map((block, blockIndex) => {
            // Cada bloque tiene un único kind por construcción: la fusión solo une
            // fragmentos del mismo tipo y nunca amplía `kinds`. Se marca AQUÍ y no en
            // un pie de sección porque 4 de las 7 secciones del informe real mezclan
            // hecho e inferencia: agregando el tipo al final, el lector no puede saber
            // qué frase es un hecho citado y cuál una conjetura del modelo, que es
            // justo la distinción que sostiene la confianza en el informe.
            const kind = block.kinds[0];
            return (
              <p
                key={`${heading}-${blockIndex}`}
                className={`report-narrative-block ${kind}`}
                data-claim-kind={kind}
              >
                <span className="report-narrative-kind">
                  {claimLabel(kind)}
                  {/* La confianza va por bloque, no agregada por sección: un rango de
                      sección mezclaría la de un hecho citado con la de una inferencia. */}
                  <small>{confidenceLabel(block.confidences)}</small>
                </span>
                {block.text}
                {!!block.evidenceIds.length && (
                  <span className="report-section-citations" aria-label="Citas del resumen">
                    {block.evidenceIds.map((evidenceId, citationIndex) =>
                      renderCitation(evidenceId, citationIndex),
                    )}
                  </span>
                )}
              </p>
            );
          })
        ) : (
          <p>No hay contenido redactado para esta sección.</p>
        )}
      </article>
    </section>
  );
}
