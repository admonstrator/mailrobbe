import { Navigate, type RouteObject } from "react-router";

import { AppShell } from "./components/AppShell";
import { DocumentDetailRoute, DocumentListRoute } from "./features/documents/lazyPages";
import { EntityDetailRoute, EntityListRoute } from "./features/entities/lazyPages";
import { GraphPage } from "./features/graph/GraphPage";
import { ImportPage } from "./features/import/ImportPage";
import { SelectorDetailRoute, SelectorListRoute } from "./features/keys/lazyPages";
import { MailDetailPage } from "./features/mail/MailDetailPage";
import { PermalinkPage } from "./features/mail/PermalinkPage";
import { MailListPage } from "./features/mails/MailListPage";
import { PersonProfilePage } from "./features/persons/PersonProfilePage";
import { PersonsPage } from "./features/persons/PersonsPage";
import { NotFoundPage } from "./features/placeholder/Placeholders";
import { AktenPage } from "./features/research/AktenPage";
import { CollectionPage } from "./features/research/CollectionPage";
import { TimelineRoute } from "./features/timeline/lazyPages";

/** One entry per screen, all inside the shell. */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/mails" replace /> },
      { path: "/mails", element: <MailListPage /> },
      { path: "/mails/:id", element: <MailDetailPage /> },
      { path: "/personen", element: <PersonsPage /> },
      { path: "/personen/:id", element: <PersonProfilePage /> },
      { path: "/anhaenge", element: <DocumentListRoute /> },
      { path: "/anhaenge/:id", element: <DocumentDetailRoute /> },
      { path: "/entitaeten", element: <EntityListRoute /> },
      { path: "/entitaeten/:id", element: <EntityDetailRoute /> },
      { path: "/karte", element: <GraphPage /> },
      { path: "/zeitachse", element: <TimelineRoute /> },
      { path: "/akten", element: <AktenPage /> },
      { path: "/akten/:id", element: <CollectionPage /> },
      { path: "/m/:hash", element: <PermalinkPage /> },
      { path: "/import", element: <ImportPage /> },
      { path: "/import/selektoren", element: <SelectorListRoute /> },
      { path: "/import/selektoren/:name", element: <SelectorDetailRoute /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
