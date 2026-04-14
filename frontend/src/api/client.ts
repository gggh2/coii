const BASE = '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

// ---- Types ----
export interface Variant {
  name: string
  provider: string
  model: string
  prompt_version?: string
  config: Record<string, unknown>
  traffic_pct: number
  is_current: boolean
}

export interface Experiment {
  id: string
  name: string
  description?: string
  status: 'draft' | 'running' | 'paused' | 'completed'
  variants: Variant[]
  outcome_events: string[]
  attribution_window_hours: number
  created_at: string
  updated_at: string
  started_at?: string
  stopped_at?: string
}

export interface VariantStats {
  name: string
  provider: string
  model: string
  prompt_version?: string
  config: Record<string, unknown>
  traffic_pct: number
  is_current: boolean
  users: number
  llm_calls: number
  avg_cost_per_call: number | null
  total_cost: number | null
  avg_latency_ms: number | null
  p50_latency_ms: number | null
  avg_input_tokens: number | null
  avg_output_tokens: number | null
  conversions: number
  conversion_rate: number
  cost_per_conversion: number | null
  z_score?: number | null
  p_value?: number | null
  is_significant?: boolean
}

export interface Recommendation {
  action: 'switch' | 'continue'
  variant?: string
  lift_pct?: number
  p_value?: number
  cost_delta_monthly_usd?: number
  message: string
}

export interface ExperimentResults {
  experiment: {
    public_id: string
    name: string
    status: string
    attribution_window_hours: number
    outcome_events: string[]
    started_at?: string
    stopped_at?: string
  }
  variants: VariantStats[]
  recommendation: Recommendation | null
  total_users: number
}

export interface Pricing {
  pricing_key: string
  input_cost_per_mtok: number
  output_cost_per_mtok: number
  source: 'builtin' | 'user'
  updated_at: string
}

export interface Provider {
  id: string
  label: string
}

export interface ModelOption {
  id: string
  label: string
}

// ---- API functions ----
export const api = {
  experiments: {
    list: () => request<Experiment[]>('GET', '/experiments'),
    get: (name: string) => request<Experiment>('GET', `/experiments/${name}`),
    create: (data: unknown) => request<Experiment>('POST', '/experiments', data),
    update: (name: string, data: unknown) => request<Experiment>('PATCH', `/experiments/${name}`, data),
    start: (name: string) => request<Experiment>('POST', `/experiments/${name}/start`),
    stop: (name: string) => request<Experiment>('POST', `/experiments/${name}/stop`),
    switch: (name: string, variantName: string) =>
      request<Experiment>('POST', `/experiments/${name}/switch`, { variant_name: variantName }),
    results: (name: string) => request<ExperimentResults>('GET', `/experiments/${name}/results`),
  },
  pricing: {
    list: () => request<Pricing[]>('GET', '/pricing'),
    upsert: (data: Pricing) => request<Pricing>('PUT', `/pricing/${data.pricing_key}`, data),
    delete: (key: string) => request<void>('DELETE', `/pricing/${key}`),
  },
  registry: {
    providers: () => request<Provider[]>('GET', '/registry/providers'),
    models: (provider?: string) =>
      request<ModelOption[]>('GET', `/registry/models${provider ? `?provider=${provider}` : ''}`),
  },
  sdk: {
    userAssignment: (userId: string, experimentName: string) =>
      request<UserAssignment>('GET', `/user-assignment?user_id=${encodeURIComponent(userId)}&experiment_name=${encodeURIComponent(experimentName)}`),
  },
}

export interface UserAssignment {
  user_id: string
  experiment: string
  assigned: boolean
  variant: string | null
  variant_config?: Variant
  exposure_id?: string
  exposed_at?: string
}
