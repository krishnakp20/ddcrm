import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import OnboardingWizard from "../components/OnboardingWizard";
import { ClientStatus, CompanyAvatar, ErrorBox, PageHead, Spinner } from "../components/ui";

/** The client's own company profile, completed after the account is activated. */
export default function Profile() {
  const { refresh } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api.get("/profile").then((r) => setData(r.data)).catch((e) => setError(errorMessage(e))), []);
  useEffect(() => { load(); }, [load]);

  const adapter = {
    save: (body) => api.put("/profile", body).then((r) => r.data),
    upload: (type, file) => { const fd = new FormData(); fd.append("doc_type", type); fd.append("file", file); return api.post("/profile/documents", fd).then((r) => r.data); },
    removeDoc: (id) => api.delete(`/profile/documents/${id}`).then((r) => r.data),
    uploadLogo: (file) => { const fd = new FormData(); fd.append("file", file); return api.post("/profile/logo", fd).then((r) => r.data); },
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;

  return (
    <>
      <PageHead title="Company profile" sub="Keep your company details and documents up to date">
        <div className="row"><CompanyAvatar name={data.company_name} logo={data.logo_url} /><b>{data.company_name}</b><ClientStatus status={data.status} /></div>
      </PageHead>
      <OnboardingWizard adapter={adapter} initial={data} lockIdentity onSaved={() => { refresh(); }} />
    </>
  );
}
