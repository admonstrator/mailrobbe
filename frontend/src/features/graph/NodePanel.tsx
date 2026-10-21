import { Link } from "react-router";

import type { Graph, GraphNode, PersonKind } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button, buttonClass } from "../../components/Button";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { nodeLabel } from "./elements";
import styles from "./NodePanel.module.css";

const KIND_LABELS: Record<PersonKind, string> = { list: "Verteiler", automated: "Automat" };

const centralityFormat = new Intl.NumberFormat("de-DE", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export interface Connection {
  other: GraphNode;
  sent: number; // from the selected node to the other, To or Bcc
  received: number;
  cc: number;
  weight: number;
}

/** The shown edges of node id, heaviest first, seen from that node. */
export function connections(graph: Graph, id: number): Connection[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  return graph.edges
    .flatMap((edge): Connection[] => {
      const outgoing = edge.source === id;
      if (!outgoing && edge.target !== id) return [];
      const other = nodes.get(outgoing ? edge.target : edge.source);
      if (!other) return [];
      return [
        {
          other,
          sent: outgoing ? edge.a_to_b : edge.b_to_a,
          received: outgoing ? edge.b_to_a : edge.a_to_b,
          cc: edge.cc,
          weight: edge.weight,
        },
      ];
    })
    .sort((a, b) => b.weight - a.weight || a.other.id - b.other.id);
}

function betweenPath(a: number, b: number): string {
  return `/mails?${new URLSearchParams([
    ["between", String(a)],
    ["between", String(b)],
  ])}`;
}

/** The right panel: figures, connections and actions of the selected node. */
export function NodePanel({
  graph,
  node,
  ccCounted,
  expanded,
  onClose,
  onExpand,
  onHide,
}: {
  graph: Graph | undefined;
  node: GraphNode | null;
  ccCounted: boolean;
  expanded: boolean;
  onClose: () => void;
  onExpand: (id: number) => void;
  onHide: (id: number) => void;
}) {
  if (!graph || !node) {
    return (
      <aside className={styles.panel} aria-label="Ausgewählte Person">
        <p className={styles.empty}>
          Klick auf einen Knoten zeigt hier seine Kennzahlen und Verbindungen. Mausrad zoomt, Ziehen
          verschiebt die Karte.
        </p>
      </aside>
    );
  }
  const links = connections(graph, node.id);
  const others = graph.nodes.length - 1;
  const centrality = others > 0 ? centralityFormat.format(links.length / others) : "–";

  return (
    <aside className={styles.panel} aria-label="Ausgewählte Person">
      <div className={styles.head}>
        <Avatar personId={node.id} name={node.name} email={node.email} />
        <div className={styles.who}>
          <strong className={styles.name}>{nodeLabel(node)}</strong>
          <span className={`mono ${styles.email}`} title={node.email}>
            {node.email}
          </span>
          {node.kind && <span className={styles.kind}>{KIND_LABELS[node.kind]}</span>}
        </div>
        <button
          type="button"
          className={styles.close}
          aria-label="Auswahl aufheben"
          onClick={onClose}
        >
          ×
        </button>
      </div>

      <dl className={styles.tiles}>
        <Tile label="Mails gesamt" value={formatNumber(node.mails)} />
        <Tile label="Kontakte" value={formatNumber(node.contacts)} />
        <Tile
          label="Im Ausschnitt"
          value={`${formatNumber(links.length)} ${links.length === 1 ? "Kante" : "Kanten"}`}
        />
        <Tile label="Zentralität" value={centrality} />
      </dl>

      <section className={styles.connections} aria-labelledby="graph-connections">
        <h2 id="graph-connections" className={styles.heading}>
          Verbindungen
        </h2>
        {links.length === 0 ? (
          <p className={styles.note}>Keine Verbindung im Ausschnitt.</p>
        ) : (
          <ul className={styles.list}>
            {links.map((link) => (
              <li key={link.other.id}>
                <Link to={betweenPath(node.id, link.other.id)} className={styles.link}>
                  <span className={styles.other}>{nodeLabel(link.other)}</span>
                  <span className={styles.figures}>
                    → {formatNumber(link.sent)} · ← {formatNumber(link.received)}
                    {ccCounted && link.cc > 0 && ` · Cc ${formatNumber(link.cc)}`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <p className={styles.note}>Klick auf eine Verbindung öffnet die Mails zwischen beiden.</p>
      </section>

      <div className={styles.actions}>
        <Link to={personPath(node.id)} className={buttonClass("primary")}>
          Profil öffnen
        </Link>
        <Button onClick={() => onExpand(node.id)} disabled={expanded}>
          {expanded ? "Nachbarn aufgeklappt" : "Nachbarn aufklappen"}
        </Button>
        {!node.center && <Button onClick={() => onHide(node.id)}>Knoten ausblenden</Button>}
      </div>
    </aside>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.tile}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
