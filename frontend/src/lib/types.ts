export interface Owner {
  id: number;
  username: string;
  display_name: string;
  accent: string;
}

export interface DatasetRow {
  id: number;
  name: string;
  description: string;
  type: "Image" | "Tabular" | "Time Series" | "Text" | "Other";
  status: "Ready" | "Processing" | "Failed";
  tags: string[];
  target_column: string | null;
  is_real: boolean;
  current_version: number;
  versions: number;
  size_bytes: number;
  samples: number;
  columns: number;
  quality: number;
  missing_pct: number;
  duplicate_pct: number;
  trainable: boolean;
  owner: Owner | null;
  created_at: string;
  updated_at: string;
}

export interface DatasetVersionInfo {
  version: number;
  size_bytes: number;
  rows: number;
  columns: number;
  quality: number;
  missing_pct: number;
  duplicate_pct: number;
  file_name: string;
  file_format: string;
  has_file: boolean;
  schema: { name: string; dtype: string; missing_pct: number; unique: number }[];
  note: string;
  created_at: string;
  owner: Owner | null;
}

export interface DatasetDetail extends DatasetRow {
  version_list: DatasetVersionInfo[];
  used_by_runs?: { id: number; code: string; status: string }[];
}

export interface DatasetStats {
  total_datasets: number;
  total_size_bytes: number;
  total_versions: number;
  delta_datasets: number;
  delta_size_bytes: number;
  delta_versions: number;
  growth: { date: string; size_bytes: number }[];
  types: { type: string; count: number }[];
  recent_uploads: {
    dataset_id: number;
    dataset: string;
    version: number;
    file_name: string;
    size_bytes: number;
    status: string;
    created_at: string;
    owner: Owner | null;
  }[];
}

export type Preview =
  | { kind: "table"; columns: string[]; rows: Record<string, unknown>[]; version: number; note: string }
  | { kind: "images"; images: string[]; version: number; note: string }
  | { kind: "none"; version: number; note: string };

export type RunStatus = "Queued" | "Training" | "Completed" | "Failed" | "Stopped";

export interface RunRow {
  id: number;
  code: string;
  name: string;
  algorithm: string;
  algorithm_label: string;
  framework: string;
  task: string;
  kind: "train" | "autotune" | "trial" | "pipeline";
  source: "live" | "seed";
  status: RunStatus;
  dataset_id: number | null;
  dataset: string | null;
  dataset_version: number | null;
  target: string | null;
  accuracy: number | null;
  loss: number | null;
  val_loss: number | null;
  f1: number | null;
  progress: number;
  epoch: number;
  total_epochs: number;
  eta_s: number | null;
  device: string;
  gpu_hours: number;
  duration_s: number;
  parent_id: number | null;
  error: string | null;
  has_artifact: boolean;
  owner: Owner | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail extends RunRow {
  params: Record<string, unknown>;
  metrics: Record<string, unknown>;
  checkpoint_path: string | null;
  artifact_path: string | null;
  trials?: RunDetail[];
  registered_as?: { model_id: number; model: string; version: string; stage: string }[];
}

export interface MetricPoint {
  epoch: number;
  train_loss: number | null;
  val_loss: number | null;
  train_acc: number | null;
  val_acc: number | null;
  f1: number | null;
}

export interface ExperimentStats {
  total: number;
  delta_total: number;
  working: number;
  delta_working: number;
  best_accuracy: number | null;
  delta_best: number | null;
  gpu_hours: number;
  delta_gpu_pct: number | null;
  spark_total: number[];
  spark_best: number[];
  spark_gpu: number[];
  model_metrics: { algorithm: string; accuracy: number }[];
}

export interface AlgorithmInfo {
  key: string;
  label: string;
  framework: string;
  default_lr: number | null;
  description: string;
}

export interface Algorithms {
  algorithms: AlgorithmInfo[];
  batch_sizes: number[];
  optimizers: string[];
  torch_available: boolean;
  gpu: string | null;
  note: string | null;
}

export type Stage = "Development" | "Staging" | "Production" | "Archived";

export interface ModelRow {
  id: number;
  name: string;
  description: string;
  tags: string[];
  framework: string;
  model_type: string;
  version: string | null;
  version_id: number | null;
  accuracy: number | null;
  size_bytes: number;
  status: Stage;
  versions: number;
  servable: boolean;
  owner: Owner | null;
  created_at: string;
  updated_at: string;
  latest_version: string | null;
}

export interface ModelVersionInfo {
  id: number;
  version: string;
  stage: Stage;
  accuracy: number | null;
  size_bytes: number;
  run_id: number | null;
  run_code: string | null;
  servable: boolean;
  description: string;
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface ModelDetail extends ModelRow {
  version_list: ModelVersionInfo[];
  deployments: { id: number; name: string; slug: string; environment: string; status: string; version: string }[];
  history: MetricPoint[];
  task: string | null;
}

export interface ModelStats {
  registered: number;
  delta_registered: number;
  production: number;
  delta_production: number;
  versions: number;
  delta_versions: number;
  avg_accuracy: number | null;
  delta_avg_accuracy: number | null;
  spark_registered: number[];
  spark_production: number[];
  spark_versions: number[];
}

export interface Lineage {
  nodes: { id: string; type: "dataset" | "run" | "model"; label: string; sub: string }[];
  edges: { id: string; source: string; target: string }[];
}

export interface DeploymentRow {
  id: number;
  slug: string;
  name: string;
  model_id: number;
  model: string;
  version_id: number;
  version: string | null;
  environment: "Production" | "Staging" | "Development";
  status: "Deploying" | "Running" | "Stopped" | "Failed";
  replicas: number;
  ready_replicas: number;
  min_replicas: number;
  max_replicas: number;
  target_cpu: number;
  rpm_per_replica: number;
  autoscaling: boolean;
  health: "Healthy" | "Degraded" | "Down" | "Stopped" | "Deploying";
  latency_ms: number | null;
  p95_ms: number | null;
  requests_24h: number;
  errors_24h: number;
  traffic_pct: number;
  sparkline: number[];
  progress: number;
  stage_label: string;
  last_error: string | null;
  endpoint: string;
  has_previous: boolean;
  owner: Owner | null;
  created_at: string;
  updated_at: string;
}

export interface DeploymentDetail extends DeploymentRow {
  history: { id: number; kind: string; version: string; environment: string; message: string; ts: string }[];
  sample_input: Record<string, unknown> | null;
  features: string[];
  task: string | null;
  classes: unknown[];
  previous_version: string | null;
  resources: { process_cpu: number; process_ram_mb: number; ram_total_gb: number; gpu: number; cpu: number; ram: number };
}

export interface PredictionLogRow {
  id: number;
  ts: string;
  latency_ms: number;
  input: Record<string, unknown>;
  prediction: unknown;
  is_error: boolean;
  error: string | null;
  replica: number;
  source: string;
}

export interface NodeState {
  status: "pending" | "running" | "success" | "failed" | "skipped" | "stopped";
  name: string;
  type: string;
  version: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  progress: number;
  message: string;
  artifacts: string[];
  run_id: number | null;
  accuracy?: number | null;
}

export interface PipelineRunInfo {
  id: number;
  number: number;
  version: string;
  triggered_by: string;
  status: "Queued" | "Running" | "Success" | "Failed" | "Stopped";
  nodes: Record<string, NodeState>;
  started_at: string;
  finished_at: string | null;
  duration_s: number;
  owner: Owner | null;
  source: string;
}

export interface PipelineNodeSpec {
  id: string;
  name: string;
  type: string;
  version: string;
  depends_on: string[];
  params: Record<string, unknown>;
}

export interface PipelineRow {
  id: number;
  name: string;
  description: string;
  version: string;
  active: boolean;
  schedule: string | null;
  next_run: string | null;
  owner: Owner | null;
  dataset: string | null;
  node_count: number;
  last_run: PipelineRunInfo | null;
  updated_at: string;
}

export interface PipelineDetail extends PipelineRow {
  yaml: string;
  spec: { name: string; version: string; dataset: string; nodes: PipelineNodeSpec[] } | null;
  spec_error: string | null;
  versions: string[];
  runs: PipelineRunInfo[];
  viewing_version: string;
}

export interface LogLine {
  id?: number;
  ts: string;
  level: string;
  node: string;
  message: string;
}

export interface AlertItem {
  id: number;
  ts: string;
  severity: "critical" | "warning" | "info" | "success";
  kind: string;
  category: string;
  title: string;
  message: string;
  deployment_id: number | null;
  read: boolean;
  resolved: boolean;
}

export interface SystemStats {
  cpu: number;
  ram: number;
  gpu: number;
  ram_used_gb: number;
  ram_total_gb: number;
  gpu_mem_used_gb: number;
  gpu_mem_total_gb: number;
  cpu_count: number;
  process_cpu: number;
  process_ram_mb: number;
  gpu_name: string | null;
  ts: string | null;
}

export interface Settings {
  workspace: { name: string; description: string; default_project: string; storage_path: string };
  appearance: { theme: "dark" | "light" | "auto"; accent: string; background: BackgroundPreset };
  compute: { target: "local" | "docker" | "aws" | "gcp"; cpu_limit: number; ram_limit: number; gpu_limit: number; autoscaling: boolean };
  notifications: { experiment_completion: boolean; job_failures: boolean; system_alerts: boolean; email: boolean; browser: boolean };
  security: { auth_method: string; session_timeout: "1h" | "8h" | "24h" | "7d"; require_auth: boolean; two_factor: boolean; team_access: boolean };
  integrations: Record<"mlflow" | "postgres" | "prometheus", { url: string }>;
  training: { pace_ms: number };
}

export type BackgroundPreset = "cosmic" | "violet" | "aurora" | "eclipse" | "nebula";

export interface SearchResult {
  type: "dataset" | "experiment" | "model" | "deployment" | "pipeline" | "user";
  id: number;
  title: string;
  subtitle: string;
  link: string;
}

export interface TeamMember {
  id: number;
  username: string;
  display_name: string;
  title: string;
  role: string;
  email: string;
  bio: string;
  location: string;
  accent: string;
  quote: string;
  joined_at: string;
}

export interface UserStats {
  datasets: number;
  dataset_versions: number;
  experiments: number;
  completed_runs: number;
  success_rate: number | null;
  best_accuracy: number | null;
  avg_accuracy: number | null;
  models: number;
  model_versions: number;
  deployments: number;
  running_deployments: number;
  pipeline_runs: number;
  gpu_hours: number;
  training_hours: number;
}

export interface UserProfile extends TeamMember {
  stats: UserStats;
  activity_series: ({ date: string; total: number } & Record<string, number | string>)[];
  contribution: { kind: string; count: number }[];
  algorithms: { algorithm: string; runs: number }[];
  recent_runs: { id: number; code: string; name: string; algorithm: string; status: RunStatus; accuracy: number | null; task: string; dataset: string | null; created_at: string }[];
  models: { id: number; name: string; version: string; stage: Stage; accuracy: number | null; framework: string; versions: number }[];
  deployments: { id: number; name: string; environment: string; status: string; version: string | null; slug: string }[];
  datasets: { id: number; name: string; type: string; status: string; size_bytes: number; updated_at: string }[];
  feed: { id: number; ts: string; kind: string; action: string; message: string; link: string }[];
  team: { username: string; display_name: string; accent: string; experiments: number; models: number; datasets: number; deployments: number; avg_accuracy: number | null }[];
  last_active: string | null;
}
