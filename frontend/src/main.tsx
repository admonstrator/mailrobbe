import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles/global.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { createQueryClient } from "./api/queries";
import { watchTheme } from "./lib/theme";
import { routes } from "./routes";

watchTheme();
const queryClient = createQueryClient();
const router = createBrowserRouter(routes);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
