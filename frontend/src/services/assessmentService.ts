import { apiClient } from '../utils/apiClient';

export type AssessmentDifficulty = 'easy' | 'medium' | 'hard';

export interface AssessmentQuestion {
  question: string;
  answer: string;
  explanation: string;
  difficulty: AssessmentDifficulty;
  question_type: string;
  concept: string;
  source_excerpt: string;
}

interface GenerateAssessmentRequest {
  user_id: string;
  lesson_title?: string;
  concept: string;
  difficulty: AssessmentDifficulty;
  question_type?: string;
  num_questions: number;
  chapter_content?: string;
  retrieved_context?: string;
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
