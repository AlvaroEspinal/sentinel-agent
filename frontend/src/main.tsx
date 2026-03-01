import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// Set Cesium Ion access token from environment
const cesiumToken = import.meta.env.VITE_CESIUM_ION_ACCESS_TOKEN || "";
if (cesiumToken && cesiumToken.length > 50) {
  try {
    const { Ion } = await import("cesium");
    Ion.defaultAccessToken = cesiumToken;
    console.log("[Parcl] Cesium Ion token configured");
  } catch (e) {
    console.warn("[Parcl] Cesium Ion setup skipped:", e);
  }
} else {
  console.warn("[Parcl] No Cesium Ion token - globe will use fallback");
}

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Remove loading screen
const loader = document.getElementById("parcl-loader");
if (loader) {
  setTimeout(() => {
    loader.classList.add("hidden");
    setTimeout(() => loader.remove(), 500);
  }, 800);
}
