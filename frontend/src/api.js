import axios from "axios";

const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !err.config.url.includes("/auth/login")) {
      localStorage.removeItem("token");
      if (window.location.pathname !== "/login") {
        const back = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${back}`;
      }
    }
    return Promise.reject(err);
  }
);

export function errorMessage(err) {
  const detail = err.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(", ");
  }
  if (detail && typeof detail === "object") return detail.message || "Request failed";
  return detail || err.message || "Something went wrong";
}

/** Field-level errors from a rejected tag form, e.g. {issue: "Required"}. */
export function fieldErrors(err) {
  const d = err.response?.data?.detail;
  return d && typeof d === "object" && !Array.isArray(d) ? d.fields || {} : {};
}

/** Opens a file that needs the login token (for example a client document) in a new tab. */
export async function openProtectedFile(path) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export default api;
