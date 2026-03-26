export interface EvaluationExperiment {
  experiment_id: string;
  name: string;
  description?: string;
  variants?: string[];
  start_time?: string;
  end_time?: string | null;
  status?: string;
  assignment_summary?: Record<string, number>;
  metrics_summary?: Record<string, unknown>;
}

export interface EvaluationExperimentListResponse {
  items: EvaluationExperiment[];
  total: number;
}

export interface EvaluationExperimentDetail extends EvaluationExperiment {
  metrics_snapshot?: {
    recommendation_ctr?: number;
    learning_path_success_rate?: number;
    shown?: number;
    clicked?: number;
    learning_path_generated?: number;
  };
}

export interface EvaluationAssignment {
  experiment_id: string;
  user_id: string;
  variant: string;
  assigned_at: string;
}
