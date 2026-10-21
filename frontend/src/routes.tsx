import { Navigate, type RouteObject } from "react-router";

import { AppShell } from "./components/AppShell";
import { GraphPage } from "./features/graph/GraphPage";
import { MailDetailPage } from "./features/mail/MailDetailPage";
import { MailListPage } from "./features/mails/MailListPage";
import {
  ImportPlaceholder,
  NotFoundPage,
  PersonPlaceholder,
  PersonsPlaceholder,
} from "./features/placeholder/Placeholders";

/** One entry per screen, all inside the shell. */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/mails" replace /> },
      { path: "/mails", element: <MailListPage /> },
      { path: "/mails/:id", element: <MailDetailPage /> },
      { path: "/personen", element: <PersonsPlaceholder /> },
      { path: "/personen/:id", element: <PersonPlaceholder /> },
      { path: "/karte", element: <GraphPage /> },
      { path: "/import", element: <ImportPlaceholder /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
