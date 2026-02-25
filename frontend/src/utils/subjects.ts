export type SubjectOption = {
  id: string;
  label: string;
  goal: string;
};

export const SUBJECTS: SubjectOption[] = [
  { id: 'python', label: 'Lập trình Python', goal: 'Học lập trình Python' },
  { id: 'cpp', label: 'Lập trình C++', goal: 'Học lập trình C++' },
  { id: 'csharp', label: 'Lập trình C#', goal: 'Học lập trình C#' },
  { id: 'java', label: 'Lập trình Java', goal: 'Học lập trình Java' },
  { id: 'javascript', label: 'Lập trình JavaScript', goal: 'Học lập trình JavaScript' },
  { id: 'web', label: 'Phát triển Web', goal: 'Học phát triển Web' },
  { id: 'data', label: 'Khoa học dữ liệu', goal: 'Học khoa học dữ liệu' }
];
