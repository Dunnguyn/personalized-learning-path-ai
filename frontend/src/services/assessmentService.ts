import { apiClient } from '../utils/apiClient';

export type AssessmentDifficulty = 'easy' | 'medium' | 'hard';

export interface AssessmentQuestion {
  question: string;
  answer: string;
  explanation: string;
  difficulty: AssessmentDifficulty;
  concept: string;
}

interface GenerateAssessmentRequest {
  user_id: string;
  concept: string;
  difficulty: AssessmentDifficulty;
  num_questions: number;
  chapter_content: string;
}

interface GenerateAssessmentResponse {
  success: boolean;
  questions: AssessmentQuestion[];
}

export const assessmentService = {
  async generateQuestions(payload: GenerateAssessmentRequest): Promise<GenerateAssessmentResponse> {
    return apiClient.post('/ask/generate-assessment', payload) as Promise<GenerateAssessmentResponse>;
  },
};
