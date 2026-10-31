import { api } from "./api";

let loading = null;

/** Load the MapmyIndia (Mappls) Web Maps SDK once, using the key the server provides. */
export function loadMappls() {
  if (typeof window !== "undefined" && window.mappls?.Map) return Promise.resolve(window.mappls);
  if (loading) return loading;
  loading = api("/api/v1/config/maps", { auth: false })
    .then((config) => {
      if (!config?.configured || !config.sdk_url) throw new Error(config?.message || "The map is not configured on the server.");
      return new Promise((resolve, reject) => {
        const fail = (message) => { clearTimeout(timer); reject(new Error(message)); };
        const timer = setTimeout(() => fail("MapmyIndia (Mappls) took too long to load. Check your connection and refresh."), 20000);
        const script = document.createElement("script");
        script.src = config.sdk_url;
        script.async = true;
        script.onerror = () => fail("MapmyIndia (Mappls) could not be loaded. The key may be invalid, not allowed for this website, or out of quota.");
        script.onload = () => {
          let tries = 0;
          const wait = () => {
            if (window.mappls?.Map) { clearTimeout(timer); resolve(window.mappls); return; }
            if ((tries += 1) > 50) { fail("MapmyIndia (Mappls) loaded but did not start. The key may not be allowed for this website."); return; }
            setTimeout(wait, 100);
          };
          wait();
        };
        document.head.appendChild(script);
      });
    })
    .catch((error) => { loading = null; throw error; });
  return loading;
}
