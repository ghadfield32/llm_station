import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

function registerStaticOnlyServiceWorker() {
  const isViteDevServer = window.location.port === "5173";
  if (!("serviceWorker" in navigator) || isViteDevServer) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("Agent Kanban service worker registration failed", err);
    });
  });
}

registerStaticOnlyServiceWorker();
