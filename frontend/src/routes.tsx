import { Navigate, type RouteObject } from "react-router";

import { AppShell } from "./components/AppShell";
import { MailDetailPage } from "./features/mail/MailDetailPage";
import { MailListPage } from "./features/mails/MailListPage";
import { PersonProfilePage } from "./features/persons/PersonProfilePage";
import { PersonsPage } from "./features/persons/PersonsPage";
import {
  GraphPlaceholder,
  ImportPlaceholder,
  NotFoundPage,
} from "./features/placeholder/Placeholders";

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
      { path: "/karte", element: <GraphPlaceholder /> },
      { path: "/import", element: <ImportPlaceholder /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
