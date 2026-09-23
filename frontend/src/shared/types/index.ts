export interface Issue { code?: string; file?: string; row?: number; field?: string; message: string }
export interface Dataset {
  id: string; label: string; synthetic: boolean; history_start: string; history_end: string;
  as_of_date: string; row_counts: Record<string, number>; warnings: (Issue | string)[];
}
export interface OrderLine {
  recommendation_id: string; sku: string; name: string; warehouse_id: string;
  unit: string; recommended_qty: number; recommended_qty_exact?: string; quantity: number | string; quantity_exact?: string; reason: string;
}
export interface Order {
  id: string; supplier_id: string; supplier_name: string; status: 'draft' | 'approved';
  version: number; created_at: string; run_id: string; lines: OrderLine[];
}
export interface Bootstrap {
  dataset: Dataset; warehouses: { warehouse_id: string; warehouse_name: string }[];
  categories: { category_id: string; category_name: string }[];
  suppliers: { supplier_id: string; supplier_name: string }[];
  runs: { run_id: string; status: string; created_at: string; dataset_id?: string }[]; orders: Order[];
}
export type Urgency = 'critical' | 'order_now' | 'reserve' | 'none' | 'review';
export interface Recommendation {
  id: string; sku: string; name: string; unit: string; warehouse_id: string; category_id: string;
  supplier_id: string; supplier_name: string; recommended_qty: number; recommended_qty_exact?: string; urgency: Urgency;
  available_stock: number; inbound_qty: number; forecast_demand: number; safety_stock: number;
  raw_requirement: number; rounding_adjustment: number; lead_time_days: number; horizon_days: number;
  base_daily_demand: number; seasonality_factor: number; growth_pct: number; moq: number;
  order_multiple: number; stockout_days: number; estimated_lost_demand: number; excluded_qty: number;
  excluded_events: number; data_warnings: string[]; explanation_steps: { label: string; value: number | string }[];
  explanation: string; chart: { date: string; observed: number; baseline: number }[];
  projection: { date: string; demand: number; stock_without_order: number; stock_with_order: number; inbound: number }[];
  seasonality: number[]; events: { date: string; qty: number; customer: string; reason: string; excluded: boolean }[];
  shortage_date: string | null; balance_requirement?: number; timing_adjustment?: number;
  seasonality_source?: string; forecast_source?: string;
  shipments?: { date: string; qty: number; id: string }[];
}
export interface CalculationSettings {
  warehouse_id: string | null; category_id: string | null; review_days: number; safety_days: number;
  use_stockout: boolean; use_outliers: boolean; use_seasonality: boolean; use_trend: boolean;
}
export interface Run {
  run_id: string; status: 'queued' | 'running' | 'completed' | 'failed'; progress: number;
  message?: string; error?: string; options?: CalculationSettings;
  result?: { recommendations: Recommendation[]; summary: Record<string, unknown> };
}
export interface ValidationReport { valid: boolean; errors: Issue[]; warnings: Issue[]; row_counts: Record<string, number> }
