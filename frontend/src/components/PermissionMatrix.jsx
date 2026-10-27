/**
 * Permission checklist grouped by area.
 *  - Role editor:  pass `value` (list of keys) and `onChange(list)`.
 *  - User editor:  pass `base` (the role's permissions) plus `extra` / `denied`; changes come back as {extra, denied}.
 * Only permissions that apply to `userType` are shown. `canGrant` limits what can be switched ON (the person
 * editing cannot give access they do not have); switching OFF is always possible.
 */
export default function PermissionMatrix({ catalog, userType, value, onChange, base, extra = [], denied = [], onOverrides, canGrant, disabled }) {
  const userMode = !!onOverrides;
  const baseSet = new Set(base || []);
  const extraSet = new Set(extra);
  const deniedSet = new Set(denied);
  const valueSet = new Set(value || []);

  const isOn = (k) => (userMode ? (baseSet.has(k) || extraSet.has(k)) && !deniedSet.has(k) : valueSet.has(k));

  function toggle(k) {
    const on = isOn(k);
    if (!userMode) {
      onChange(on ? [...valueSet].filter((x) => x !== k) : [...valueSet, k]);
      return;
    }
    let e = new Set(extraSet), d = new Set(deniedSet);
    if (on) {
      if (e.has(k)) e.delete(k); else d.add(k);   // switch off: drop the grant, or deny what the role gives
    } else {
      if (d.has(k)) d.delete(k); else e.add(k);   // switch on: lift the denial, or grant on top of the role
    }
    onOverrides({ extra: [...e], denied: [...d] });
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      {catalog.map((g) => {
        const items = g.permissions.filter((p) => p.types.includes(userType));
        if (!items.length) return null;
        return (
          <div key={g.group}>
            <div className="section-title" style={{ marginBottom: 6 }}>{g.group}</div>
            {items.map((p) => {
              const on = isOn(p.key);
              const blocked = disabled || (!on && canGrant && !canGrant.has(p.key));
              let tag = null;
              if (userMode && extraSet.has(p.key) && !baseSet.has(p.key)) tag = <span className="badge active">added for this user</span>;
              if (userMode && deniedSet.has(p.key) && baseSet.has(p.key)) tag = <span className="badge rejected">removed for this user</span>;
              return (
                <label key={p.key} className="perm-row" title={blocked && !on && !disabled ? "You cannot give access you do not have yourself" : undefined}
                  style={{ opacity: blocked && !on ? 0.55 : 1 }}>
                  <input type="checkbox" checked={on} disabled={blocked} onChange={() => toggle(p.key)} />
                  <span className="grow">
                    <span style={{ fontWeight: 600 }}>{p.label}</span>
                    {p.hint && <span className="small muted" style={{ display: "block" }}>{p.hint}</span>}
                  </span>
                  {tag}
                  <span className="mono muted" style={{ fontSize: 11 }}>{p.key}</span>
                </label>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
