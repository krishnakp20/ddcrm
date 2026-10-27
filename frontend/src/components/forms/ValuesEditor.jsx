import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../../api";
import { ErrorBox, Modal, Spinner } from "../ui";

/**
 * Edit the values of a list, one column per level (Country | State | City).
 * Click a value to see and edit what is under it. `canEdit` false = view only.
 */
export default function ValuesEditor({ listId, onClose, canEdit = true }) {
  const [list, setList] = useState(null);
  const [cols, setCols] = useState([]);          // cols[i] = items of level i+1 under the chosen parent
  const [picked, setPicked] = useState([]);      // picked[i] = the chosen item of level i+1
  const [drafts, setDrafts] = useState({});      // text typed in each column's "add" box
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState("");

  const fetchLevel = useCallback(async (parentId) => {
    const { data } = await api.get(`/value-lists/${listId}/items`, { params: { parent_id: parentId ?? undefined } });
    return data;
  }, [listId]);

  useEffect(() => {
    (async () => {
      try {
        const [meta, first] = await Promise.all([api.get(`/value-lists/${listId}`), fetchLevel(null)]);
        setList(meta.data);
        setCols([first]);
      } catch (e) { setError(errorMessage(e)); }
    })();
  }, [listId, fetchLevel]);

  async function pick(level, item) {
    const nextPicked = [...picked.slice(0, level - 1), item];
    setPicked(nextPicked);
    const kids = await fetchLevel(item.id);
    setCols([...cols.slice(0, level), kids]);
  }

  async function reloadColumn(level) {
    const parent = level === 1 ? null : picked[level - 2]?.id;
    const data = await fetchLevel(parent);
    setCols((c) => c.map((col, i) => (i === level - 1 ? data : col)));
  }

  async function add(level) {
    const label = (drafts[level] || "").trim();
    if (!label) return;
    setError(""); setBusy(true);
    try {
      await api.post(`/value-lists/${listId}/items`, { label, parent_id: level === 1 ? null : picked[level - 2].id });
      setDrafts({ ...drafts, [level]: "" });
      await reloadColumn(level);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  async function rename(level, item) {
    const label = window.prompt("New name", item.label);
    if (!label || label.trim() === item.label) return;
    try { await api.put(`/value-items/${item.id}`, { label, is_active: item.is_active }); await reloadColumn(level); }
    catch (e) { setError(errorMessage(e)); }
  }

  async function toggle(level, item) {
    try { await api.put(`/value-items/${item.id}`, { label: item.label, is_active: !item.is_active }); await reloadColumn(level); }
    catch (e) { setError(errorMessage(e)); }
  }

  async function remove(level, item) {
    const extra = item.children_count ? ` Everything under it (${item.children_count}) is removed too.` : "";
    if (!window.confirm(`Delete “${item.label}”?${extra}`)) return;
    try {
      await api.delete(`/value-items/${item.id}`);
      if (picked[level - 1]?.id === item.id) { setPicked(picked.slice(0, level - 1)); setCols(cols.slice(0, level)); }
      await reloadColumn(level);
    } catch (e) { setError(errorMessage(e)); }
  }

  async function upload(file) {
    if (!file) return;
    setError(""); setInfo(""); setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("header", "true");
    try {
      const { data } = await api.post(`/value-lists/${listId}/import`, fd);
      setInfo(`Imported: ${data.added} values added${data.skipped ? `, ${data.skipped} rows skipped` : ""}.`);
      setPicked([]);
      setCols([await fetchLevel(null)]);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  if (!list) return <Modal title="Values" onClose={onClose} wide>{error ? <ErrorBox error={error} /> : <Spinner />}</Modal>;
  const levelNames = list.level_names.length ? list.level_names : ["Values"];

  return (
    <Modal title={`Values: ${list.name}`} onClose={onClose} wide
      footer={<>
        {canEdit && (
          <span className="btn file-btn" style={{ marginRight: "auto" }}>
            {busy ? "Working…" : "Import CSV / Excel"}
            <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => { upload(e.target.files[0]); e.target.value = ""; }} />
          </span>
        )}
        <button className="btn btn-primary" onClick={onClose}>Done</button>
      </>}>
      <ErrorBox error={error} />
      {info && <div className="alert success" style={{ marginBottom: 10 }}>{info}</div>}
      {canEdit && levelNames.length > 1 && <p className="muted small" style={{ marginTop: 0 }}>
        To import, use one column per level ({levelNames.join(", ")}) and a header row.</p>}
      <div className="values-grid" style={{ gridTemplateColumns: `repeat(${levelNames.length}, minmax(180px, 1fr))` }}>
        {levelNames.map((name, i) => {
          const level = i + 1;
          const enabled = level === 1 || !!picked[level - 2];
          const items = cols[i];
          return (
            <div key={level} className="values-col">
              <div className="values-head">{name}</div>
              {!enabled ? <div className="small muted" style={{ padding: 10 }}>Pick a {levelNames[level - 2]} first</div> : (
                <>
                  {canEdit && (
                    <div className="row gap-sm" style={{ padding: 8 }}>
                      <input placeholder={`Add ${name.toLowerCase()}`} value={drafts[level] || ""} onChange={(e) => setDrafts({ ...drafts, [level]: e.target.value })}
                        onKeyDown={(e) => e.key === "Enter" && add(level)} />
                      <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => add(level)}>Add</button>
                    </div>
                  )}
                  <div className="values-items">
                    {!items ? <Spinner label="" /> : items.length === 0 ? <div className="small muted" style={{ padding: 10 }}>Nothing here yet</div> : items.map((it) => (
                      <div key={it.id} className={`values-item ${picked[i]?.id === it.id ? "on" : ""} ${it.is_active ? "" : "off"}`} onClick={() => level < levelNames.length && pick(level, it)}>
                        <span className="grow">{it.label}{it.children_count > 0 && <span className="muted small"> · {it.children_count}</span>}</span>
                        {canEdit && (
                          <span className="row gap-sm" onClick={(e) => e.stopPropagation()}>
                            <button className="btn btn-sm btn-ghost" title="Rename" onClick={() => rename(level, it)}>✎</button>
                            <button className="btn btn-sm btn-ghost" title={it.is_active ? "Switch off" : "Switch on"} onClick={() => toggle(level, it)}>{it.is_active ? "●" : "○"}</button>
                            <button className="btn btn-sm btn-ghost" title="Delete" onClick={() => remove(level, it)}>✕</button>
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
