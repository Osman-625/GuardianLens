// Side panel entry point: loads the shared design styles, then the panel's own styles, and mounts
// the React app into #root.
import "@guardianlens/shared/styles.css";
import "./panel.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
