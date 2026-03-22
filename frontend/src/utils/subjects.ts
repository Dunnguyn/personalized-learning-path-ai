export type SubjectOption = {
  id: string;
  label: string;
  goal: string;
};

export const SUBJECTS: SubjectOption[] = [
  { id: 'python', label: 'L\u1eadp tr\u00ecnh Python', goal: 'H\u1ecdc l\u1eadp tr\u00ecnh Python' },
  { id: 'cpp', label: 'L\u1eadp tr\u00ecnh C++', goal: 'H\u1ecdc l\u1eadp tr\u00ecnh C++' },
  { id: 'csharp', label: 'L\u1eadp tr\u00ecnh C#', goal: 'H\u1ecdc l\u1eadp tr\u00ecnh C#' },
  { id: 'java', label: 'L\u1eadp tr\u00ecnh Java', goal: 'H\u1ecdc l\u1eadp tr\u00ecnh Java' },
  { id: 'web', label: 'Ph\u00e1t tri\u1ec3n Web', goal: 'H\u1ecdc ph\u00e1t tri\u1ec3n Web' }
];
