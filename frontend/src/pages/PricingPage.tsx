import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Pricing } from '../api/client'
import { Pencil, Check, X, Trash2, Plus } from 'lucide-react'

export function PricingPage() {
  const qc = useQueryClient()
  const { data: pricing, isLoading } = useQuery({ queryKey: ['pricing'], queryFn: api.pricing.list })

  const [editing, setEditing] = useState<string | null>(null)
  const [editValues, setEditValues] = useState({ input: '', output: '' })
  const [newKey, setNewKey] = useState('')
  const [newInput, setNewInput] = useState('')
  const [newOutput, setNewOutput] = useState('')
  const [addOpen, setAddOpen] = useState(false)

  const upsertMutation = useMutation({
    mutationFn: api.pricing.upsert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pricing'] })
      setEditing(null)
      setNewKey(''); setNewInput(''); setNewOutput('')
      setAddOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: api.pricing.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pricing'] }),
  })

  function startEdit(p: Pricing) {
    setEditing(p.pricing_key)
    setEditValues({ input: p.input_cost_per_mtok.toString(), output: p.output_cost_per_mtok.toString() })
  }

  function saveEdit(key: string) {
    upsertMutation.mutate({
      pricing_key: key,
      input_cost_per_mtok: parseFloat(editValues.input),
      output_cost_per_mtok: parseFloat(editValues.output),
      source: 'user',
      updated_at: new Date().toISOString(),
    })
  }

  function addNew() {
    if (!newKey || !newInput || !newOutput) return
    upsertMutation.mutate({
      pricing_key: newKey,
      input_cost_per_mtok: parseFloat(newInput),
      output_cost_per_mtok: parseFloat(newOutput),
      source: 'user',
      updated_at: new Date().toISOString(),
    })
  }

  const builtins = pricing?.filter(p => p.source === 'builtin') ?? []
  const overrides = pricing?.filter(p => p.source === 'user') ?? []

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '40px 32px' }}>
      {/* Header */}
      <div className="fade-up fade-up-1" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 className="font-serif" style={{ fontSize: 28, letterSpacing: '-0.02em', color: 'var(--ink)', marginBottom: 6 }}>
            Model Pricing
          </h1>
          <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>
            Cost per million tokens. User overrides take precedence over built-in rates.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setAddOpen(o => !o)}>
          <Plus size={13} /> Add override
        </button>
      </div>

      {/* Add form */}
      {addOpen && (
        <div className="card fade-up" style={{ marginBottom: 16, overflow: 'hidden' }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.02em' }}>
              Add / override pricing
            </span>
          </div>
          <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 140px 140px auto', gap: 12, alignItems: 'end' }}>
            <div>
              <label className="label">Pricing key (provider/model)</label>
              <input className="input-base" value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="openai/gpt-4o" data-testid="new-pricing-key" style={{ fontFamily: 'IBM Plex Mono', fontSize: 12 }} />
            </div>
            <div>
              <label className="label">Input $/M tokens</label>
              <input type="number" step="0.01" className="input-base" value={newInput} onChange={e => setNewInput(e.target.value)} data-testid="new-pricing-input" style={{ fontFamily: 'IBM Plex Mono', textAlign: 'right' }} />
            </div>
            <div>
              <label className="label">Output $/M tokens</label>
              <input type="number" step="0.01" className="input-base" value={newOutput} onChange={e => setNewOutput(e.target.value)} data-testid="new-pricing-output" style={{ fontFamily: 'IBM Plex Mono', textAlign: 'right' }} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn-primary" onClick={addNew} disabled={upsertMutation.isPending} data-testid="add-pricing-btn">Save</button>
              <button className="btn-ghost" onClick={() => setAddOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* User overrides */}
      {overrides.length > 0 && (
        <div className="card fade-up fade-up-2" style={{ marginBottom: 16, overflow: 'hidden', borderColor: '#cde0ff' }}>
          <div style={{ padding: '12px 20px', borderBottom: '1px solid #cde0ff', background: 'var(--accent-light)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              User overrides
            </span>
            <span style={{ fontSize: 11, color: 'var(--accent)', opacity: 0.7 }}>
              {overrides.length} {overrides.length === 1 ? 'override' : 'overrides'}
            </span>
          </div>
          <PricingTable
            rows={overrides}
            editing={editing}
            editValues={editValues}
            onEdit={startEdit}
            onSave={saveEdit}
            onCancel={() => setEditing(null)}
            onDelete={key => deleteMutation.mutate(key)}
            onEditChange={(f, v) => setEditValues(ev => ({ ...ev, [f]: v }))}
          />
        </div>
      )}

      {/* Built-in pricing */}
      <div className="card fade-up fade-up-3" style={{ overflow: 'hidden' }}>
        <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Built-in pricing
          </span>
          <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>
            {builtins.length} models · click pencil to override
          </span>
        </div>
        {isLoading ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>Loading…</div>
        ) : (
          <PricingTable
            rows={builtins}
            editing={editing}
            editValues={editValues}
            onEdit={startEdit}
            onSave={saveEdit}
            onCancel={() => setEditing(null)}
            onDelete={undefined}
            onEditChange={(f, v) => setEditValues(ev => ({ ...ev, [f]: v }))}
          />
        )}
      </div>

      <div style={{ height: 40 }} />
    </div>
  )
}

interface PricingTableProps {
  rows: Pricing[]
  editing: string | null
  editValues: { input: string; output: string }
  onEdit: (p: Pricing) => void
  onSave: (key: string) => void
  onCancel: () => void
  onDelete: ((key: string) => void) | undefined
  onEditChange: (field: 'input' | 'output', val: string) => void
}

function PricingTable({ rows, editing, editValues, onEdit, onSave, onCancel, onDelete, onEditChange }: PricingTableProps) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th style={{ textAlign: 'left' }}>Pricing key</th>
          <th>Input ($/M tok)</th>
          <th>Output ($/M tok)</th>
          <th>Updated</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(p => (
          <tr key={p.pricing_key} data-testid={`pricing-row-${p.pricing_key}`}>
            <td>
              <span style={{ fontFamily: 'IBM Plex Mono', fontSize: 12, color: 'var(--ink-2)' }}>{p.pricing_key}</span>
            </td>
            <td>
              {editing === p.pricing_key ? (
                <input
                  type="number"
                  step="0.01"
                  value={editValues.input}
                  onChange={e => onEditChange('input', e.target.value)}
                  style={{ width: 80, border: '1px solid var(--accent)', borderRadius: 4, padding: '3px 7px', fontFamily: 'IBM Plex Mono', fontSize: 12, textAlign: 'right', outline: 'none' }}
                />
              ) : (
                <span className="stat-num">${p.input_cost_per_mtok.toFixed(2)}</span>
              )}
            </td>
            <td>
              {editing === p.pricing_key ? (
                <input
                  type="number"
                  step="0.01"
                  value={editValues.output}
                  onChange={e => onEditChange('output', e.target.value)}
                  style={{ width: 80, border: '1px solid var(--accent)', borderRadius: 4, padding: '3px 7px', fontFamily: 'IBM Plex Mono', fontSize: 12, textAlign: 'right', outline: 'none' }}
                />
              ) : (
                <span className="stat-num">${p.output_cost_per_mtok.toFixed(2)}</span>
              )}
            </td>
            <td>
              <span style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'IBM Plex Mono' }}>
                {new Date(p.updated_at).toLocaleDateString()}
              </span>
            </td>
            <td>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
                {editing === p.pricing_key ? (
                  <>
                    <ActionBtn onClick={() => onSave(p.pricing_key)} title="Save" color="var(--green)">
                      <Check size={12} />
                    </ActionBtn>
                    <ActionBtn onClick={onCancel} title="Cancel">
                      <X size={12} />
                    </ActionBtn>
                  </>
                ) : (
                  <>
                    <ActionBtn onClick={() => onEdit(p)} title="Edit">
                      <Pencil size={11} />
                    </ActionBtn>
                    {onDelete && (
                      <ActionBtn onClick={() => onDelete(p.pricing_key)} title="Delete" hoverColor="var(--red)">
                        <Trash2 size={11} />
                      </ActionBtn>
                    )}
                  </>
                )}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ActionBtn({ onClick, children, title, color = 'var(--ink-3)', hoverColor }: {
  onClick: () => void; children: React.ReactNode; title: string; color?: string; hoverColor?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{ display: 'flex', alignItems: 'center', padding: 5, borderRadius: 4, border: 'none', background: 'transparent', cursor: 'pointer', color }}
      onMouseEnter={e => { if (hoverColor) e.currentTarget.style.color = hoverColor; e.currentTarget.style.background = 'var(--surface-3)' }}
      onMouseLeave={e => { e.currentTarget.style.color = color; e.currentTarget.style.background = 'transparent' }}
    >
      {children}
    </button>
  )
}
