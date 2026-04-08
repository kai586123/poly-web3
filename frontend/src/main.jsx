import "antd/dist/reset.css";
import { ConfigProvider } from "antd";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

function readServerDefaults() {
  const node = document.getElementById("server-defaults");
  if (!node) {
    return {};
  }
  try {
    return JSON.parse(node.textContent || "{}");
  } catch (_error) {
    return {};
  }
}

const rootNode = document.getElementById("root");
if (!rootNode) {
  throw new Error("missing #root container");
}

createRoot(rootNode).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#2f7df4",
          borderRadius: 12,
          fontFamily: "'Plus Jakarta Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        },
      }}
    >
      <App serverDefaults={readServerDefaults()} />
    </ConfigProvider>
  </React.StrictMode>,
);
