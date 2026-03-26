import { apiClient } from '../utils/apiClient';
import type {
  EvaluationAssignment,
  EvaluationExperimentDetail,
  EvaluationExperimentListResponse,
} from '../types/evaluation';

export const evaluationService = {
  async listExperiments(): Promise<EvaluationExperimentListResponse> {
    return (await apiClient.get('/evaluation/experiments')) as EvaluationExperimentListResponse;
  },

  async getExperiment(experimentId: string): Promise<EvaluationExperimentDetail> {
    return (await apiClient.get(
      `/evaluation/experiments/${encodeURIComponent(experimentId)}`,
    )) as EvaluationExperimentDetail;
  },

  async assignVariant(experimentId: string, userId: string): Promise<EvaluationAssignment> {
    return (await apiClient.post(
      `/evaluation/experiments/${encodeURIComponent(experimentId)}/assign/${encodeURIComponent(userId)}`,
    )) as EvaluationAssignment;
  },
};
