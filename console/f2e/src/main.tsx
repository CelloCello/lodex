import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./app";
import "./style.css";
import { applyTheme, readTheme } from "./lib/theme";

applyTheme(readTheme());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The loopback server is usable even without an internet connection.
      networkMode: "always",
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>,
);
