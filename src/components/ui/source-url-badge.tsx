/** G06 · etiqueta honesta para source_urls (nunca «verificada» sin fetch). */

export type SourceUrlMetaLike = {
  url: string;
  label?: string | null;
  status?: string | null;
  verified?: boolean | null;
};

export function SourceUrlList({
  urls,
  meta,
  label = "no verificada",
}: {
  urls?: string[] | null;
  meta?: SourceUrlMetaLike[] | null;
  label?: string;
}) {
  const items: SourceUrlMetaLike[] =
    meta && meta.length > 0
      ? meta
      : (urls ?? []).map((url) => ({ url, label, status: "no_verificada", verified: false }));

  if (items.length === 0) {
    return <span className="muted">Sin URLs de respaldo</span>;
  }

  return (
    <ul className="source-url-list" data-testid="source-url-list">
      {items.map((item) => (
        <li key={item.url}>
          <a href={item.url} rel="noreferrer noopener" target="_blank">
            {item.url}
          </a>{" "}
          <span className="source-url-badge" data-testid="source-url-unverified-badge">
            {item.label || label}
          </span>
        </li>
      ))}
    </ul>
  );
}
